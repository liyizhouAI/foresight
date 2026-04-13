"""
图谱构建服务
接口2：使用 Graphiti + Neo4j 构建知识图谱（替代 Zep Cloud）
"""

import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from .graphiti_client import GraphitiClient
from .text_processor import TextProcessor
from ..utils.locale import t, get_locale, set_locale


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    图谱构建服务
    使用 Graphiti + Neo4j 构建知识图谱
    """

    def __init__(self, api_key: Optional[str] = None):
        # api_key kept for interface compatibility but unused
        self.client = GraphitiClient.get_instance()
        self.task_manager = TaskManager()

    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "Foresight Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3
    ) -> str:
        """异步构建图谱，返回任务ID"""
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )

        current_locale = get_locale()

        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size, current_locale)
        )
        thread.daemon = True
        thread.start()

        return task_id

    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
        locale: str = 'zh'
    ):
        """图谱构建工作线程"""
        set_locale(locale)
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message=t('progress.startBuildingGraph')
            )

            # 1. 创建图谱（分配 group_id）
            graph_id = self.client.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=t('progress.graphCreated', graphId=graph_id)
            )

            # 2. 准备本体类型（Graphiti 使用 Pydantic 模型）
            entity_types, edge_types = self._prepare_ontology(ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message=t('progress.ontologySet')
            )

            # 3. 文本分块
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )

            # 4. 逐个添加 episode（Graphiti 同步处理，不需要轮询）
            def progress_cb(msg, prog):
                self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.65),  # 20-85%
                    message=msg
                )

            self.client.add_episodes_batch(
                graph_id=graph_id,
                texts=chunks,
                source_description=graph_name,
                entity_types=entity_types,
                edge_types=edge_types,
                progress_callback=progress_cb,
            )

            # 5. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message=t('progress.fetchingGraphInfo')
            )

            graph_info = self._get_graph_info(graph_id)

            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)

    def create_graph(self, name: str) -> str:
        """创建图谱（公开方法）"""
        return self.client.create_graph(name)

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（Graphiti 在 add_episode 时传入，此方法保留兼容性）"""
        # Graphiti doesn't have a separate set_ontology step;
        # ontology is passed per add_episode call.
        # Store it for later use.
        self._stored_ontology = ontology

    def _prepare_ontology(self, ontology: Dict[str, Any]) -> tuple:
        """
        将前端本体格式转换为 Graphiti Pydantic 模型格式

        Returns:
            (entity_types dict, edge_types dict) for Graphiti
        """
        from pydantic import BaseModel, Field
        from typing import Optional as Opt

        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")

            # Build Pydantic model dynamically
            attrs = {}
            annotations = {}
            for attr_def in entity_def.get("attributes", []):
                attr_name = attr_def["name"]
                # Skip reserved names
                if attr_name.lower() in {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}:
                    attr_name = f"entity_{attr_name}"
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Opt[str]

            attrs["__annotations__"] = annotations
            attrs["__doc__"] = description
            entity_class = type(name, (BaseModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class

        edge_types = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")

            attrs = {}
            annotations = {}
            for attr_def in edge_def.get("attributes", []):
                attr_name = attr_def["name"]
                if attr_name.lower() in {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}:
                    attr_name = f"edge_{attr_name}"
                attr_desc = attr_def.get("description", attr_name)
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Opt[str]

            attrs["__annotations__"] = annotations
            attrs["__doc__"] = description
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (BaseModel,), attrs)
            edge_class.__doc__ = description
            edge_types[name] = edge_class

        return entity_types if entity_types else None, edge_types if edge_types else None

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """分批添加文本到图谱，返回 episode IDs"""
        self.client.add_episodes_batch(
            graph_id=graph_id,
            texts=chunks,
            progress_callback=progress_callback,
        )
        # Graphiti doesn't return episode UUIDs the same way
        return [f"ep_{i}" for i in range(len(chunks))]

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        nodes = self.client.get_all_nodes(graph_id)
        edges = self.client.get_all_edges(graph_id)

        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node", "__Entity__"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types)
        )

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """获取完整图谱数据"""
        nodes = self.client.get_all_nodes(graph_id)
        edges = self.client.get_all_edges(graph_id)

        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""

        nodes_data = []
        for node in nodes:
            nodes_data.append({
                "uuid": node.uuid_,
                "name": node.name,
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": node.created_at,
            })

        edges_data = []
        for edge in edges:
            edges_data.append({
                "uuid": edge.uuid_,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": edge.name or "",
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "source_node_name": node_map.get(edge.source_node_uuid, ""),
                "target_node_name": node_map.get(edge.target_node_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": edge.created_at,
                "valid_at": edge.valid_at,
                "invalid_at": edge.invalid_at,
                "expired_at": edge.expired_at,
                "episodes": edge.episodes or [],
            })

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self.client.delete_graph(graph_id)
