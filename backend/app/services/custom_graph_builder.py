"""
Custom Graph Builder - 替换 Graphiti 的自建实现

核心设计：
1. 文本切分（字符级简单切分，与 TextProcessor 一致）
2. 对每个 chunk，单次 LLM 调用抽取 entities + relationships
3. 去重（按 entity name）
4. 直接用 neo4j driver 写入
5. 不使用 embedding、reranker、Graphiti 的任何代码
"""

import re
import uuid
import concurrent.futures
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from neo4j import GraphDatabase

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('foresight.custom_graph_builder')


class CustomGraphBuilder:
    """
    用 LLM + Neo4j 自建图谱构建器。

    替代 Graphiti，保持下游 GraphitiClient.get_all_nodes / get_all_edges 接口兼容。
    写入 schema：
      Node : Entity [可选第二 label]  properties: uuid, name, summary, group_id, created_at
      Edge : 任意类型                  properties: uuid, name, fact, group_id, created_at
    """

    def __init__(self, graph_id: str, ontology: Dict[str, Any]):
        """
        Args:
            graph_id: 图谱唯一标识（group_id）
            ontology: {"entity_types": [...], "edge_types": [...]}
        """
        self.graph_id = graph_id
        self.ontology = ontology or {"entity_types": [], "edge_types": []}

        self.llm = LLMClient()

        self.driver = GraphDatabase.driver(
            Config.NEO4J_URI,
            auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD),
        )

        self.entities_created = 0
        self.edges_created = 0
        # 去重：entity name → uuid
        self._entity_uuid_by_name: Dict[str, str] = {}

    def close(self):
        if self.driver:
            self.driver.close()

    def ensure_constraints(self):
        """
        建索引保证 MERGE 效率。
        每条 DDL 独立 try/except 包住 — Graphiti 可能已经建过同名普通 index，
        而我们想要的是 unique constraint。冲突时跳过，不让初始化挂掉。
        """
        ddls = [
            "CREATE CONSTRAINT entity_uuid_unique IF NOT EXISTS "
            "FOR (n:Entity) REQUIRE n.uuid IS UNIQUE",
            "CREATE INDEX entity_name_idx IF NOT EXISTS "
            "FOR (n:Entity) ON (n.name)",
            "CREATE INDEX entity_group_idx IF NOT EXISTS "
            "FOR (n:Entity) ON (n.group_id)",
        ]
        with self.driver.session() as session:
            for ddl in ddls:
                try:
                    session.run(ddl)
                except Exception as e:
                    # IndexAlreadyExists / ConstraintAlreadyExists 等都是无害的
                    logger.warning(
                        f"CustomGraphBuilder: DDL skipped ({type(e).__name__}): "
                        f"{str(e)[:150]}"
                    )

    # ------------------------------------------------------------------ #
    #  LLM 抽取
    # ------------------------------------------------------------------ #

    def _build_extraction_prompt(self, chunk_text: str) -> str:
        entity_types_desc = "\n".join(
            f"- {(t.get('name', t) if isinstance(t, dict) else t)}: "
            f"{(t.get('description', '') if isinstance(t, dict) else '')}"
            for t in self.ontology.get("entity_types", [])[:20]
        ) or "- Entity: 任何有意义的实体（人、组织、概念、事件、产品等）"

        edge_types_desc = "\n".join(
            f"- {(t.get('name', t) if isinstance(t, dict) else t)}: "
            f"{(t.get('description', '') if isinstance(t, dict) else '')}"
            for t in self.ontology.get("edge_types", [])[:20]
        ) or "- 任何合理的关系类型"

        return (
            "你是一个知识图谱构建助手。从下面文本中抽取实体和关系。\n\n"
            "## 实体类型\n\n"
            f"{entity_types_desc}\n\n"
            "## 关系类型参考\n\n"
            f"{edge_types_desc}\n\n"
            "## 文本\n\n"
            f"{chunk_text}\n\n"
            "## 输出格式\n\n"
            "严格返回 JSON，不要有任何其他文字：\n\n"
            "```json\n"
            "{\n"
            '  "entities": [\n'
            '    {\n'
            '      "name": "实体名（必须，简洁，禁止嵌套对象）",\n'
            '      "type": "实体类型名（从上面列表里选，或用 Entity）",\n'
            '      "summary": "一句话描述这个实体（纯文本字符串，禁止嵌套对象，最多 200 字）"\n'
            '    }\n'
            '  ],\n'
            '  "relationships": [\n'
            '    {\n'
            '      "source": "源实体名（必须和 entities 里某个 name 一致）",\n'
            '      "target": "目标实体名",\n'
            '      "type": "关系类型（大写下划线格式，如 WORKS_AT, MENTIONS）",\n'
            '      "fact": "一句话描述这个关系（纯文本，最多 150 字）"\n'
            '    }\n'
            '  ]\n'
            '}\n'
            "```\n\n"
            "重要规则：\n"
            "- 所有字段必须是字符串 primitive，禁止嵌套 dict / object / list\n"
            "- entities 每条的 name 要全局唯一\n"
            "- relationships 里的 source/target 必须在 entities 里存在\n"
            '- 如果没找到任何实体，返回 {"entities": [], "relationships": []}\n'
            "- 实体数量控制在 5-20 之间\n"
            "- 关系数量控制在 0-30 之间\n"
        )

    def extract_from_chunk(self, chunk_text: str) -> Dict[str, List[Dict]]:
        """对一个 chunk 做 LLM 抽取，返回 {entities, relationships}"""
        prompt = self._build_extraction_prompt(chunk_text)
        messages = [
            {"role": "system", "content": "你是一个严谨的知识图谱构建助手，只返回 JSON。"},
            {"role": "user", "content": prompt},
        ]
        try:
            result = self.llm.chat_json(messages, temperature=0.3, max_tokens=4096)
            if not isinstance(result, dict):
                logger.warning(f"chunk 返回非 dict: {type(result)}")
                return {"entities": [], "relationships": []}
            return {
                "entities": result.get("entities", []) if isinstance(result.get("entities"), list) else [],
                "relationships": result.get("relationships", []) if isinstance(result.get("relationships"), list) else [],
            }
        except Exception as e:
            logger.error(f"chunk LLM 抽取失败: {type(e).__name__}: {str(e)[:200]}")
            return {"entities": [], "relationships": []}

    # ------------------------------------------------------------------ #
    #  sanitize helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sanitize_value(v: Any) -> Any:
        """把 LLM 返回的字段 flatten 成 primitive"""
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, dict):
            if "value" in v:
                return CustomGraphBuilder._sanitize_value(v["value"])
            return str(v)[:500]
        if isinstance(v, list):
            return ", ".join(str(x)[:100] for x in v)[:500]
        return str(v)[:500]

    @staticmethod
    def _safe_label(raw: str, default: str) -> str:
        """清洗字符串用作 Neo4j label / relationship type"""
        cleaned = re.sub(r"[^A-Za-z0-9_]", "", raw)
        return cleaned if cleaned else default

    # ------------------------------------------------------------------ #
    #  Neo4j writes
    # ------------------------------------------------------------------ #

    def upsert_entity(self, tx, entity: Dict) -> Optional[str]:
        """写入或更新实体节点，返回 uuid；同名实体幂等合并"""
        name = self._sanitize_value(entity.get("name", ""))
        if not isinstance(name, str):
            name = str(name)
        name = name.strip()
        if not name:
            return None

        if name in self._entity_uuid_by_name:
            return self._entity_uuid_by_name[name]

        entity_uuid = str(uuid.uuid4())
        raw_type = self._sanitize_value(entity.get("type", "Entity")) or "Entity"
        if not isinstance(raw_type, str):
            raw_type = str(raw_type)
        safe_type = self._safe_label(raw_type.strip(), "Entity")
        summary = self._sanitize_value(entity.get("summary", "")) or ""
        if not isinstance(summary, str):
            summary = str(summary)
        summary = summary[:1000]

        extra_label = f":{safe_type}" if safe_type != "Entity" else ""

        tx.run(
            f"""
            MERGE (n:Entity{extra_label} {{name: $name, group_id: $gid}})
            ON CREATE SET
                n.uuid = $uuid,
                n.summary = $summary,
                n.created_at = $created_at
            ON MATCH SET
                n.summary = CASE
                    WHEN n.summary IS NULL OR n.summary = '' THEN $summary
                    ELSE n.summary
                END
            """,
            name=name,
            gid=self.graph_id,
            uuid=entity_uuid,
            summary=summary,
            created_at=datetime.utcnow().isoformat(),
        )
        self._entity_uuid_by_name[name] = entity_uuid
        self.entities_created += 1
        return entity_uuid

    def upsert_relationship(self, tx, rel: Dict) -> bool:
        """写入关系边；source/target 必须已在 _entity_uuid_by_name 中"""
        source_name = self._sanitize_value(rel.get("source", ""))
        target_name = self._sanitize_value(rel.get("target", ""))
        if not isinstance(source_name, str):
            source_name = str(source_name)
        if not isinstance(target_name, str):
            target_name = str(target_name)
        source_name = source_name.strip()
        target_name = target_name.strip()

        if not source_name or not target_name:
            return False
        if source_name not in self._entity_uuid_by_name or target_name not in self._entity_uuid_by_name:
            return False

        raw_type = self._sanitize_value(rel.get("type", "RELATED_TO")) or "RELATED_TO"
        if not isinstance(raw_type, str):
            raw_type = str(raw_type)
        safe_type = self._safe_label(raw_type.strip().upper(), "RELATED_TO")

        fact = self._sanitize_value(rel.get("fact", "")) or ""
        if not isinstance(fact, str):
            fact = str(fact)
        fact = fact[:800]

        rel_uuid = str(uuid.uuid4())

        tx.run(
            f"""
            MATCH (a:Entity {{name: $src, group_id: $gid}}),
                  (b:Entity {{name: $tgt, group_id: $gid}})
            MERGE (a)-[r:{safe_type} {{uuid: $uuid}}]->(b)
            ON CREATE SET
                r.name = $rel_name,
                r.fact = $fact,
                r.group_id = $gid,
                r.created_at = $created_at
            """,
            src=source_name,
            tgt=target_name,
            gid=self.graph_id,
            uuid=rel_uuid,
            rel_name=safe_type,
            fact=fact,
            created_at=datetime.utcnow().isoformat(),
        )
        self.edges_created += 1
        return True

    # ------------------------------------------------------------------ #
    #  Main entry
    # ------------------------------------------------------------------ #

    def build(
        self,
        full_text: str,
        chunk_size: int = 250,
        chunk_overlap: int = 50,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        concurrency: int = 10,
    ) -> Dict[str, Any]:
        """
        主入口：分 chunk → **并发** LLM 抽取 → 写 Neo4j

        v0.3.2 并发化改动：
        - LLM 抽取用 ThreadPoolExecutor 并发 (默认 10 线程)
        - Neo4j 写入串行 (单 session + dict 去重必须顺序执行避免 name 冲突)
        - LLM 调用走 Foresight LLMClient，自带 retry/backoff/fallback 抗限流

        Args:
            full_text: 合并后的完整文档文本
            chunk_size: 每块字符数
            chunk_overlap: 块之间重叠字符数
            progress_callback: 进度回调 (current, total, message)
            concurrency: LLM 抽取并发数 (默认 10，建议 5-15)

        Returns:
            {"entities_count": N, "edges_count": M, "chunks_processed": K,
             "chunks_failed": F, "total_chunks": T}
        """
        self.ensure_constraints()

        # token 追踪
        try:
            from ..utils import token_tracker
            token_tracker.set_stage("step2_graph_build")
        except Exception:
            pass

        # 字符级切分
        chunks: List[str] = []
        start = 0
        while start < len(full_text):
            end = min(start + chunk_size, len(full_text))
            chunks.append(full_text[start:end])
            if end == len(full_text):
                break
            start = end - chunk_overlap

        total_chunks = len(chunks)
        logger.info(
            f"CustomGraphBuilder: {total_chunks} chunks, "
            f"concurrency={concurrency}, graph_id={self.graph_id}"
        )

        processed = 0
        failed = 0
        progress_lock = threading.Lock()
        completed = [0]

        def _extract_one(idx_chunk):
            """worker: LLM 抽取一个 chunk，返回 (idx, extracted)"""
            idx, chunk_text = idx_chunk
            try:
                return idx, self.extract_from_chunk(chunk_text)
            except Exception as e:
                logger.error(
                    f"chunk {idx + 1} LLM 抽取线程异常: "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )
                return idx, {"entities": [], "relationships": []}

        # 步骤1: 并发抽取全部 chunks
        # 用单个持久 session 做 Neo4j 写入，按完成顺序消费结果
        with self.driver.session() as session:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_map = {
                    executor.submit(_extract_one, (i, c)): i
                    for i, c in enumerate(chunks)
                }

                for future in concurrent.futures.as_completed(future_map):
                    idx = future_map[future]
                    try:
                        _idx, extracted = future.result()
                    except Exception as e:
                        logger.error(f"chunk {idx + 1} future 异常: {e}")
                        failed += 1
                        continue

                    entities = extracted.get("entities", [])
                    relationships = extracted.get("relationships", [])

                    # 进度上报
                    with progress_lock:
                        completed[0] += 1
                        current = completed[0]
                    if progress_callback:
                        progress_callback(
                            current,
                            total_chunks,
                            f"处理 chunk {current}/{total_chunks}",
                        )

                    if not entities and not relationships:
                        processed += 1
                        continue

                    # Neo4j 写入（串行，避免同名 entity 并发插入冲突）
                    try:
                        def _tx_write(tx, _ents=entities, _rels=relationships):
                            for e in _ents:
                                if isinstance(e, dict):
                                    self.upsert_entity(tx, e)
                            for r in _rels:
                                if isinstance(r, dict):
                                    self.upsert_relationship(tx, r)

                        session.execute_write(_tx_write)
                        processed += 1
                    except Exception as e:
                        logger.error(
                            f"chunk {idx + 1} 写 Neo4j 失败: "
                            f"{type(e).__name__}: {str(e)[:200]}"
                        )
                        failed += 1

        logger.info(
            f"CustomGraphBuilder 完成: entities={self.entities_created}, "
            f"edges={self.edges_created}, chunks={processed}/{total_chunks}, "
            f"failed={failed}"
        )

        return {
            "entities_count": self.entities_created,
            "edges_count": self.edges_created,
            "chunks_processed": processed,
            "chunks_failed": failed,
            "total_chunks": total_chunks,
        }
