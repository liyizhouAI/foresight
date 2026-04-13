"""
Graphiti 知识图谱客户端
替代 Zep Cloud，使用自托管的 Graphiti + Neo4j

Graphiti 是 async 库，本模块提供同步包装供 Flask 使用。
"""

import asyncio
import uuid
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

from neo4j import GraphDatabase

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('foresight.graphiti_client')

# Global event loop for async bridge
_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """Get or create a dedicated event loop for Graphiti async calls."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def _run_async(coro):
    """Run an async coroutine synchronously."""
    loop = _get_loop()
    return loop.run_until_complete(coro)


@dataclass
class GraphitiNode:
    """Node data from Neo4j, compatible with Zep node format."""
    uuid_: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None

    @property
    def uuid(self):
        return self.uuid_


@dataclass
class GraphitiEdge:
    """Edge data from Neo4j, compatible with Zep edge format."""
    uuid_: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    episodes: Optional[List[str]] = None

    @property
    def uuid(self):
        return self.uuid_


class GraphitiClient:
    """
    Graphiti + Neo4j 知识图谱客户端

    提供与原 Zep Cloud 兼容的接口:
    - create_graph / delete_graph
    - add_episodes (文本导入)
    - search (语义搜索)
    - get_all_nodes / get_all_edges
    - get_node / get_node_edges
    """

    _instance: Optional['GraphitiClient'] = None
    _graphiti = None
    _initialized = False

    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
    ):
        self.neo4j_uri = neo4j_uri or Config.NEO4J_URI
        self.neo4j_user = neo4j_user or Config.NEO4J_USER
        self.neo4j_password = neo4j_password or Config.NEO4J_PASSWORD

        # Neo4j driver for direct queries
        self._driver = GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        logger.info(f"GraphitiClient initialized: {self.neo4j_uri}")

    def _ensure_graphiti(self):
        """Lazy-init Graphiti (imports are heavy)."""
        if self._graphiti is not None:
            return

        from graphiti_core import Graphiti
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.llm_client.config import LLMConfig

        llm_config = LLMConfig(
            api_key=Config.LLM_API_KEY,
            model=Config.LLM_MODEL_NAME,
            small_model=Config.LLM_MODEL_NAME,
            base_url=Config.LLM_BASE_URL,
        )
        llm_client = OpenAIGenericClient(config=llm_config)

        self._graphiti = Graphiti(
            self.neo4j_uri,
            self.neo4j_user,
            self.neo4j_password,
            llm_client=llm_client,
        )
        # Build indices
        _run_async(self._graphiti.build_indices_and_constraints())
        self._initialized = True
        logger.info("Graphiti core initialized with indices")

    @classmethod
    def get_instance(cls) -> 'GraphitiClient':
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ========== Graph CRUD ==========

    def create_graph(self, name: str) -> str:
        """Create a logical graph (just returns a group_id, Neo4j doesn't need explicit creation)."""
        graph_id = f"foresight_{uuid.uuid4().hex[:16]}"
        logger.info(f"Created graph group: {graph_id} ({name})")
        return graph_id

    def delete_graph(self, graph_id: str):
        """Delete all nodes and edges belonging to a graph group."""
        with self._driver.session() as session:
            # Delete edges first, then nodes
            session.run(
                "MATCH (a)-[r]-(b) WHERE r.group_id = $gid DELETE r",
                gid=graph_id,
            )
            session.run(
                "MATCH (n) WHERE n.group_id = $gid DETACH DELETE n",
                gid=graph_id,
            )
        logger.info(f"Deleted graph: {graph_id}")

    # ========== Episode ingestion ==========

    def add_episode(
        self,
        graph_id: str,
        text: str,
        source_description: str = "document",
        entity_types: Optional[Dict] = None,
        edge_types: Optional[Dict] = None,
    ):
        """Add a single text episode to the graph."""
        self._ensure_graphiti()

        kwargs = {
            "name": f"episode_{uuid.uuid4().hex[:8]}",
            "episode_body": text,
            "source_description": source_description,
            "reference_time": datetime.now(timezone.utc),
            "group_id": graph_id,
        }
        if entity_types:
            kwargs["entity_types"] = entity_types
        if edge_types:
            kwargs["edge_types"] = edge_types

        from graphiti_core.nodes import EpisodeType
        kwargs["source"] = EpisodeType.text

        _run_async(self._graphiti.add_episode(**kwargs))

    def add_episodes_batch(
        self,
        graph_id: str,
        texts: List[str],
        source_description: str = "document",
        entity_types: Optional[Dict] = None,
        edge_types: Optional[Dict] = None,
        progress_callback=None,
    ):
        """Add multiple text episodes sequentially (Graphiti processes one at a time)."""
        total = len(texts)
        for i, text in enumerate(texts):
            if progress_callback:
                progress_callback(
                    f"Processing episode {i + 1}/{total}",
                    (i + 1) / total,
                )
            try:
                self.add_episode(
                    graph_id, text, source_description,
                    entity_types, edge_types,
                )
            except Exception as e:
                logger.error(f"Failed to add episode {i + 1}/{total}: {e}")
                raise
            # Small delay to avoid rate limiting
            if i < total - 1:
                time.sleep(0.5)

    # ========== Search ==========

    def search(
        self,
        query: str,
        graph_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search the graph for relevant edges/facts."""
        self._ensure_graphiti()

        kwargs = {"query": query, "num_results": limit}
        if graph_id:
            kwargs["group_ids"] = [graph_id]

        results = _run_async(self._graphiti.search(**kwargs))

        facts = []
        for edge in results:
            facts.append({
                "uuid": str(getattr(edge, 'uuid', '')),
                "fact": getattr(edge, 'fact', ''),
                "name": getattr(edge, 'name', ''),
                "source_node_uuid": str(getattr(edge, 'source_node_uuid', '')),
                "target_node_uuid": str(getattr(edge, 'target_node_uuid', '')),
            })
        return facts

    # ========== Node/Edge queries (direct Neo4j) ==========

    def get_all_nodes(self, graph_id: str, limit: int = 2000) -> List[GraphitiNode]:
        """Get all entity nodes for a graph group."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (n:Entity)
                WHERE n.group_id = $gid
                RETURN n, labels(n) as labels
                ORDER BY n.name
                LIMIT $limit
                """,
                gid=graph_id,
                limit=limit,
            )
            nodes = []
            for record in result:
                n = record["n"]
                raw_labels = record["labels"]
                # Filter internal labels
                labels = [l for l in raw_labels if l not in ("__Entity__",)]
                nodes.append(GraphitiNode(
                    uuid_=str(n.get("uuid", n.element_id)),
                    name=n.get("name", ""),
                    labels=labels,
                    summary=n.get("summary", ""),
                    attributes=dict(n) if n else {},
                    created_at=str(n.get("created_at", "")) if n.get("created_at") else None,
                ))
            return nodes

    def get_all_edges(self, graph_id: str) -> List[GraphitiEdge]:
        """Get all edges for a graph group."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a)-[r:RELATES_TO]->(b)
                WHERE r.group_id = $gid
                RETURN r, a.uuid as source_uuid, b.uuid as target_uuid
                """,
                gid=graph_id,
            )
            edges = []
            for record in result:
                r = record["r"]
                edges.append(GraphitiEdge(
                    uuid_=str(r.get("uuid", r.element_id)),
                    name=r.get("name", ""),
                    fact=r.get("fact", ""),
                    source_node_uuid=str(record["source_uuid"] or ""),
                    target_node_uuid=str(record["target_uuid"] or ""),
                    attributes=dict(r) if r else {},
                    created_at=str(r.get("created_at", "")) if r.get("created_at") else None,
                    valid_at=str(r.get("valid_at", "")) if r.get("valid_at") else None,
                    invalid_at=str(r.get("invalid_at", "")) if r.get("invalid_at") else None,
                    expired_at=str(r.get("expired_at", "")) if r.get("expired_at") else None,
                ))
            return edges

    def get_node(self, node_uuid: str) -> Optional[GraphitiNode]:
        """Get a single node by UUID."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (n:Entity {uuid: $uuid})
                RETURN n, labels(n) as labels
                """,
                uuid=node_uuid,
            )
            record = result.single()
            if not record:
                return None
            n = record["n"]
            labels = [l for l in record["labels"] if l not in ("__Entity__",)]
            return GraphitiNode(
                uuid_=str(n.get("uuid", n.element_id)),
                name=n.get("name", ""),
                labels=labels,
                summary=n.get("summary", ""),
                attributes=dict(n) if n else {},
                created_at=str(n.get("created_at", "")) if n.get("created_at") else None,
            )

    def get_node_edges(self, node_uuid: str) -> List[GraphitiEdge]:
        """Get all edges connected to a specific node."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a)-[r:RELATES_TO]-(b)
                WHERE a.uuid = $uuid
                RETURN r,
                       CASE WHEN startNode(r) = a THEN a.uuid ELSE b.uuid END as source_uuid,
                       CASE WHEN startNode(r) = a THEN b.uuid ELSE a.uuid END as target_uuid
                """,
                uuid=node_uuid,
            )
            edges = []
            for record in result:
                r = record["r"]
                edges.append(GraphitiEdge(
                    uuid_=str(r.get("uuid", r.element_id)),
                    name=r.get("name", ""),
                    fact=r.get("fact", ""),
                    source_node_uuid=str(record["source_uuid"] or ""),
                    target_node_uuid=str(record["target_uuid"] or ""),
                    attributes=dict(r) if r else {},
                ))
            return edges

    def close(self):
        """Close connections."""
        if self._driver:
            self._driver.close()
        if self._graphiti:
            try:
                _run_async(self._graphiti.close())
            except Exception:
                pass
        logger.info("GraphitiClient closed")
