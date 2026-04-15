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

# ============================================================
# LOWEST-LEVEL PATCH: neo4j AsyncSession + AsyncTransaction
# ============================================================
_NEO4J_DRIVER_PATCHED = False


def _sanitize_value(v):
    """Recursively flatten a value to a Neo4j-safe primitive."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        # LLM JSON-schema pollution: {description, title, type, value} → extract value
        if "value" in v:
            return _sanitize_value(v["value"])
        # Plain dict cannot be a Neo4j property → serialize as JSON string
        import json as _json
        return _json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return [_sanitize_value(x) for x in v]
    return str(v)


def _sanitize_params(params):
    """Sanitize all values in a cypher parameters dict."""
    if not isinstance(params, dict):
        return params
    return {k: _sanitize_value(v) for k, v in params.items()}


def _patch_neo4j_driver():
    """
    Ultimate fallback: patch neo4j AsyncSession.run and AsyncTransaction.run
    to sanitize all parameters before they reach the Neo4j wire protocol.

    This catches every cypher call regardless of which graphiti path is taken.
    """
    global _NEO4J_DRIVER_PATCHED
    if _NEO4J_DRIVER_PATCHED:
        return

    try:
        from neo4j import AsyncSession, AsyncTransaction

        _orig_session_run = AsyncSession.run

        async def _patched_session_run(self, query, parameters=None, **kwargs):
            sanitized = _sanitize_params(parameters) if parameters is not None else parameters
            sanitized_kw = {k: _sanitize_value(v) for k, v in kwargs.items()} if kwargs else kwargs
            return await _orig_session_run(self, query, sanitized, **sanitized_kw)

        AsyncSession.run = _patched_session_run

        _orig_tx_run = AsyncTransaction.run

        async def _patched_tx_run(self, query, parameters=None, **kwargs):
            sanitized = _sanitize_params(parameters) if parameters is not None else parameters
            sanitized_kw = {k: _sanitize_value(v) for k, v in kwargs.items()} if kwargs else kwargs
            return await _orig_tx_run(self, query, sanitized, **sanitized_kw)

        AsyncTransaction.run = _patched_tx_run

        _NEO4J_DRIVER_PATCHED = True
        logger.info("[Foresight] Patched neo4j AsyncSession.run + AsyncTransaction.run for nested-dict sanitization")

    except Exception as _e:
        # Never let patch failure crash Flask startup
        logger.warning(f"[Foresight] neo4j driver patch failed (non-fatal): {_e}")


# Patch immediately at import time — before any graphiti code runs
_patch_neo4j_driver()


def _safe_str(val):
    """Convert any value to JSON-safe string, handling Neo4j DateTime etc."""
    if val is None:
        return None
    return str(val)


def _flatten_entity_property(value):
    """
    Flatten a potentially nested dict/list value into a Neo4j-safe primitive.

    Priority:
    1. Primitive (str/int/float/bool/None) → return as-is
    2. dict with "value" key → recurse into value (handles LLM JSON-schema pollution)
    3. dict → json.dumps
    4. list → flatten each element recursively
    5. Other → str()
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        if "value" in value:
            return _flatten_entity_property(value["value"])
        import json
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return [_flatten_entity_property(v) for v in value]
    return str(value)


def _sanitize_entity_data(entity_data: dict) -> dict:
    """Sanitize all values in entity_data dict to Neo4j-safe primitives."""
    return {k: _flatten_entity_property(v) for k, v in entity_data.items()}


from graphiti_core.embedder.client import EmbedderClient


class MiniMaxEmbedder(EmbedderClient):
    """
    Custom embedder for MiniMax API.
    Implements Graphiti's EmbedderClient interface.
    MiniMax uses 'texts' field instead of OpenAI's 'input' field.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.minimax.chat/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "embo-01", "texts": texts, "type": "db"},
            )
            response.raise_for_status()
            return response.json().get("vectors", [])

    async def create(self, input_data) -> list[float]:
        """Create embedding for a single text. Returns one vector."""
        if isinstance(input_data, str):
            texts = [input_data]
        elif isinstance(input_data, list) and input_data and isinstance(input_data[0], str):
            texts = [input_data[0]]
        else:
            texts = [str(input_data)]
        vectors = await self._call_api(texts)
        return vectors[0] if vectors else []

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """Create embeddings for multiple texts."""
        return await self._call_api(input_data_list)


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


def _patch_reranker_for_non_openai(reranker):
    """
    Patch OpenAIRerankerClient.rank() to be compatible with providers that don't support
    logprobs / top_logprobs / logit_bias (e.g. GLM-4-Flash, MiniMax).

    The original implementation uses logprobs to get True/False probabilities.
    This patch replaces it with a simple text-based True/False prompt that works
    with any OpenAI-compatible provider.

    Root cause of GLM code 20015: Graphiti sends logprobs=True + top_logprobs=2
    + logit_bias which GLM rejects with "The parameter is invalid."
    """
    try:
        import numpy as np
        from graphiti_core.helpers import semaphore_gather
        from graphiti_core.llm_client import RateLimitError
        import openai as _openai

        client_obj = reranker.client
        model_name = reranker.config.model or "glm-4-flash"

        async def _compatible_rank(query: str, passages: list[str]) -> list[tuple[str, float]]:
            if not passages:
                return []

            openai_messages_list = [
                [
                    {
                        "role": "system",
                        "content": "You are an expert tasked with determining whether the passage is relevant to the query",
                    },
                    {
                        "role": "user",
                        "content": (
                            'Respond with only "True" if PASSAGE is relevant to QUERY and "False" otherwise.\n'
                            f"<PASSAGE>\n{passage}\n</PASSAGE>\n"
                            f"<QUERY>\n{query}\n</QUERY>"
                        ),
                    },
                ]
                for passage in passages
            ]

            try:
                responses = await semaphore_gather(
                    *[
                        client_obj.chat.completions.create(
                            model=model_name,
                            messages=openai_messages,
                            temperature=0,
                            max_tokens=5,
                        )
                        for openai_messages in openai_messages_list
                    ]
                )

                results = []
                for passage, response in zip(passages, responses):
                    text = response.choices[0].message.content or ""
                    score = 1.0 if "true" in text.strip().lower() else 0.0
                    results.append((passage, score))

                results.sort(reverse=True, key=lambda x: x[1])
                return results

            except _openai.RateLimitError as e:
                raise RateLimitError from e
            except Exception as e:
                import logging as _logging
                _logging.getLogger(__name__).error(f"[Foresight] Reranker error: {e}")
                # Fallback: return all passages with equal score (no reranking)
                return [(p, 0.5) for p in passages]

        reranker.rank = _compatible_rank
        logger.info("[Foresight] Patched OpenAIRerankerClient.rank() for non-OpenAI provider compatibility (no logprobs)")

    except Exception as e:
        logger.warning(f"[Foresight] Failed to patch reranker (non-fatal): {e}")


def _patch_embedder_empty_input(embedder):
    """
    Patch OpenAIEmbedder.create_batch to guard against empty input lists.

    Root cause of code 20015 from SiliconFlow: Graphiti calls create_batch([]) when
    there are no nodes to embed (e.g. create_entity_node_embeddings with empty list).
    SiliconFlow (and GLM) return error 20015 for empty input arrays.

    Fix: return [] immediately if input is empty, without calling the API.
    """
    try:
        orig_create_batch = embedder.create_batch

        async def guarded_create_batch(input_data_list):
            if not input_data_list:
                return []
            return await orig_create_batch(input_data_list)

        embedder.create_batch = guarded_create_batch
        logger.info("[Foresight] Patched OpenAIEmbedder.create_batch to guard empty input (fixes code 20015)")

    except Exception as e:
        logger.warning(f"[Foresight] Failed to patch embedder (non-fatal): {e}")


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

        # Re-apply driver patch (idempotent) in case import order caused it to run
        # before neo4j was available, or the class got re-imported.
        _patch_neo4j_driver()

        from graphiti_core import Graphiti
        from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
        from graphiti_core.llm_client.config import LLMConfig

        # Use SiliconFlow LLM for Graphiti (better structured output support)
        graphiti_api_key = Config.GRAPHITI_LLM_API_KEY or Config.LLM_API_KEY
        graphiti_base_url = Config.GRAPHITI_LLM_BASE_URL or Config.LLM_BASE_URL
        graphiti_model = Config.GRAPHITI_LLM_MODEL or Config.LLM_MODEL_NAME

        llm_config = LLMConfig(
            api_key=graphiti_api_key,
            model=graphiti_model,
            small_model=graphiti_model,
            base_url=graphiti_base_url,
        )
        llm_client = OpenAIGenericClient(config=llm_config)

        # Embedder: SiliconFlow free BAAI/bge-m3 (OpenAI-compatible)
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        embedder_config = OpenAIEmbedderConfig(
            api_key=Config.EMBEDDING_API_KEY or Config.LLM_API_KEY,
            base_url=Config.EMBEDDING_BASE_URL or "https://api.siliconflow.cn/v1",
            embedding_model=Config.EMBEDDING_MODEL or "BAAI/bge-m3",
            embedding_dim=1024,
        )
        embedder = OpenAIEmbedder(config=embedder_config)

        # Reranker: use the LLM config
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
        reranker = OpenAIRerankerClient(config=llm_config)

        # Patch reranker if the provider doesn't support logprobs (e.g. GLM, MiniMax)
        _patch_reranker_for_non_openai(reranker)

        # Patch embedder to guard against empty input (SiliconFlow/GLM return 20015 for [])
        _patch_embedder_empty_input(embedder)

        self._graphiti = Graphiti(
            self.neo4j_uri,
            self.neo4j_user,
            self.neo4j_password,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=reranker,
        )

        # Monkey-patch Neo4j entity node ops to sanitize LLM-polluted summary fields
        # before they reach Neo4j (which rejects non-primitive property values).
        self._patch_entity_node_ops()

        # Build indices
        _run_async(self._graphiti.build_indices_and_constraints())
        self._initialized = True
        logger.info("Graphiti core initialized with indices")

    def _patch_entity_node_ops(self):
        """
        Patch both EntityNode.save (single-episode path) and
        bulk_utils.add_nodes_and_edges_bulk_tx (bulk/batch episode path) to sanitize
        entity_data before writing to Neo4j.

        Root cause: Qwen/other LLMs return JSON-schema metadata dicts in fields like
        'summary' instead of plain strings. e.g.:
            {"summary": {"description": "...", "title": "Summary", "type": "string", "value": "actual text"}}

        The bulk path builds entity_data dicts and passes them directly via tx.run()
        without calling EntityNode.save at all, so we must patch both paths.
        """
        # --- Patch 1: EntityNode.save (single-episode path) ---
        from graphiti_core.nodes import EntityNode

        original_save = EntityNode.save

        async def patched_save(self_node, driver):
            if isinstance(self_node.summary, (dict, list)):
                self_node.summary = _flatten_entity_property(self_node.summary)
            if self_node.attributes:
                self_node.attributes = _sanitize_entity_data(self_node.attributes)
            return await original_save(self_node, driver)

        EntityNode.save = patched_save
        logger.info("[Foresight] Patched EntityNode.save for single-episode sanitization")

        # --- Patch 2: add_nodes_and_edges_bulk_tx (bulk episode path) ---
        import graphiti_core.utils.bulk_utils as _bulk_utils
        from typing import Any as _Any

        original_bulk_tx = _bulk_utils.add_nodes_and_edges_bulk_tx

        async def patched_bulk_tx(tx, episodic_nodes, episodic_edges, entity_nodes,
                                  entity_edges, embedder):
            # Sanitize each entity node's summary and attributes in-place before
            # original function builds entity_data dicts from them
            for node in entity_nodes:
                if isinstance(node.summary, (dict, list)):
                    node.summary = _flatten_entity_property(node.summary)
                if node.attributes:
                    node.attributes = _sanitize_entity_data(node.attributes)
            return await original_bulk_tx(tx, episodic_nodes, episodic_edges,
                                          entity_nodes, entity_edges, embedder)

        _bulk_utils.add_nodes_and_edges_bulk_tx = patched_bulk_tx
        logger.info("[Foresight] Patched add_nodes_and_edges_bulk_tx for bulk-episode sanitization")

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
        """Add multiple text episodes using bulk API for parallel processing."""
        self._ensure_graphiti()
        total = len(texts)
        import time as _time

        # Use bulk API for parallel processing (much faster)
        BULK_SIZE = 5  # Process 5 episodes in parallel per batch

        for batch_start in range(0, total, BULK_SIZE):
            batch_texts = texts[batch_start:batch_start + BULK_SIZE]
            batch_end = min(batch_start + BULK_SIZE, total)

            if progress_callback:
                progress_callback(
                    f"正在并行处理第 {batch_start + 1}-{batch_end}/{total} 个文本块...",
                    batch_start / total,
                )

            start = _time.time()
            try:
                from graphiti_core.utils.bulk_utils import RawEpisode
                from graphiti_core.nodes import EpisodeType

                raw_episodes = [
                    RawEpisode(
                        name=f"episode_{batch_start + i}",
                        content=text,
                        source_description=source_description,
                        source=EpisodeType.text,
                        reference_time=datetime.now(timezone.utc),
                    )
                    for i, text in enumerate(batch_texts)
                ]

                _run_async(self._graphiti.add_episode_bulk(
                    bulk_episodes=raw_episodes,
                    group_id=graph_id,
                    entity_types=entity_types,
                    edge_types=edge_types,
                ))
            except Exception as e:
                logger.warning(f"Bulk failed for batch {batch_start}-{batch_end}, falling back to sequential: {e}")
                # Fallback: process one by one
                for i, text in enumerate(batch_texts):
                    try:
                        self.add_episode(graph_id, text, source_description, entity_types, edge_types)
                    except Exception as e2:
                        logger.error(f"Episode {batch_start + i + 1}/{total} failed: {e2}")
                        continue

            elapsed = _time.time() - start
            logger.info(f"Batch {batch_start + 1}-{batch_end}/{total} processed in {elapsed:.1f}s ({len(batch_texts)} episodes)")

            if progress_callback:
                progress_callback(
                    f"第 {batch_start + 1}-{batch_end}/{total} 处理完成（{len(batch_texts)}块用时 {elapsed:.0f}s）",
                    batch_end / total,
                )

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
                    attributes={k: _safe_str(v) for k, v in dict(n).items()} if n else {},
                    created_at=_safe_str(n.get("created_at")),
                ))
            return nodes

    def get_all_edges(self, graph_id: str) -> List[GraphitiEdge]:
        """Get all edges for a graph group."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE r.group_id = $gid
                RETURN r, type(r) as rtype, a.uuid as source_uuid, b.uuid as target_uuid
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
                    attributes={k: _safe_str(v) for k, v in dict(r).items()} if r else {},
                    created_at=_safe_str(r.get("created_at")),
                    valid_at=_safe_str(r.get("valid_at")),
                    invalid_at=_safe_str(r.get("invalid_at")),
                    expired_at=_safe_str(r.get("expired_at")),
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
                attributes={k: _safe_str(v) for k, v in dict(n).items()} if n else {},
                created_at=_safe_str(n.get("created_at")),
            )

    def get_node_edges(self, node_uuid: str) -> List[GraphitiEdge]:
        """Get all edges connected to a specific node."""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a)-[r]-(b)
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
