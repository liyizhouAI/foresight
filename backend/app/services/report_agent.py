"""
Report Agent 服务

使用 ReACT 模式的模拟报告生成 Agent。
Prompts → report_prompts.py | Data classes → report_data.py | Analytics → simulation_analytics.py
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional, Callable

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..utils.locale import get_language_instruction, t

from .zep_tools import ZepToolsService
from .simulation_analytics import SimulationAnalyticsService

from .report_prompts import (
    TOOL_DESC_SIMULATION_ANALYTICS,
    TOOL_DESC_INSIGHT_FORGE,
    TOOL_DESC_PANORAMA_SEARCH,
    TOOL_DESC_QUICK_SEARCH,
    TOOL_DESC_INTERVIEW_AGENTS,
    PLAN_SYSTEM_PROMPT,
    PLAN_USER_PROMPT_TEMPLATE,
    SECTION_SYSTEM_PROMPT_TEMPLATE,
    SECTION_USER_PROMPT_TEMPLATE,
    REACT_OBSERVATION_TEMPLATE,
    REACT_INSUFFICIENT_TOOLS_MSG,
    REACT_INSUFFICIENT_TOOLS_MSG_ALT,
    REACT_TOOL_LIMIT_MSG,
    REACT_UNUSED_TOOLS_HINT,
    REACT_FORCE_FINAL_MSG,
    CHAT_SYSTEM_PROMPT_TEMPLATE,
    CHAT_OBSERVATION_SUFFIX,
)

from .report_data import (
    ReportStatus,
    ReportSection,
    ReportOutline,
    Report,
    ReportLogger,
    ReportConsoleLogger,
    ReportManager,
)

logger = get_logger('foresight.report_agent')


class ReportAgent:
    """
    Report Agent — 模拟报告生成 Agent

    ReACT 模式：规划 → 逐章节生成（工具调用 + LLM）→ 组装
    """

    MAX_TOOL_CALLS_PER_SECTION = 5
    MAX_REFLECTION_ROUNDS = 3
    MAX_TOOL_CALLS_PER_CHAT = 2

    def __init__(
        self,
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None,
    ):
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement

        self.llm = llm_client or LLMClient(
            api_key=os.environ.get("REPORT_LLM_API_KEY") or None,
            base_url=os.environ.get("REPORT_LLM_BASE_URL") or None,
            model=os.environ.get("REPORT_LLM_MODEL_NAME") or None,
        )
        self.zep_tools = zep_tools or ZepToolsService(llm_client=self.llm)
        self.analytics = SimulationAnalyticsService()
        self.tools = self._define_tools()

        self.report_logger: Optional[ReportLogger] = None
        self.console_logger: Optional[ReportConsoleLogger] = None

        logger.info(t('report.agentInitDone', graphId=graph_id, simulationId=simulation_id))

    # ── Tool Definitions ──

    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        return {
            "simulation_analytics": {
                "name": "simulation_analytics",
                "description": TOOL_DESC_SIMULATION_ANALYTICS,
                "parameters": {
                    "query_type": "查询类型: overview_stats, top_posts, agent_quotes, action_distribution, engagement_metrics, sentiment_breakdown",
                    "n": "返回数量（可选，默认10）",
                },
            },
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "你想深入分析的问题或话题",
                    "report_context": "当前报告章节的上下文（可选）",
                },
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "搜索查询，用于相关性排序",
                    "include_expired": "是否包含过期/历史内容（默认True）",
                },
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "搜索查询字符串",
                    "limit": "返回结果数量（可选，默认10）",
                },
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "采访主题或需求描述",
                    "max_agents": "最多采访的Agent数量（可选，默认5）",
                },
            },
        }

    VALID_TOOL_NAMES = {
        "simulation_analytics", "insight_forge", "panorama_search",
        "quick_search", "interview_agents",
    }

    # ── Tool Execution ──

    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any],
                      report_context: str = "") -> str:
        logger.info(t('report.executingTool', toolName=tool_name, params=parameters))
        try:
            if tool_name == "simulation_analytics":
                query_type = parameters.get("query_type", "overview_stats")
                n = parameters.get("n", 10)
                if isinstance(n, str):
                    n = int(n)
                result = self.analytics.get_analytics(
                    simulation_id=self.simulation_id,
                    query_type=query_type,
                    n=n,
                )
                return json.dumps(result, ensure_ascii=False, indent=2)

            elif tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id, query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx,
                )
                return result.to_text()

            elif tool_name == "panorama_search":
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ('true', '1', 'yes')
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id, query=query,
                    include_expired=include_expired,
                )
                return result.to_text()

            elif tool_name == "quick_search":
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id, query=query, limit=limit,
                )
                return result.to_text()

            elif tool_name == "interview_agents":
                topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=min(max_agents, 10),
                )
                return result.to_text()

            # Backward compat aliases
            elif tool_name == "search_graph":
                return self._execute_tool("quick_search", parameters, report_context)
            elif tool_name == "get_simulation_context":
                query = parameters.get("query", self.simulation_requirement)
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            elif tool_name == "get_entity_summary":
                name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id, entity_name=name,
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            elif tool_name == "get_entities_by_type":
                etype = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id, entity_type=etype,
                )
                return json.dumps([n.to_dict() for n in nodes], ensure_ascii=False, indent=2)
            else:
                return f"未知工具: {tool_name}。请使用: simulation_analytics, insight_forge, panorama_search, quick_search, interview_agents"

        except Exception as e:
            logger.error(t('report.toolExecFailed', toolName=tool_name, error=str(e)))
            return f"工具执行失败: {str(e)}"

    # ── Tool Call Parsing ──

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        tool_calls = []

        # Format 1: XML-style
        xml_pattern = r'edisnormal\s*(\{.*?\})\s*edisnormal'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                tool_calls.append(json.loads(match.group(1)))
            except json.JSONDecodeError:
                pass
        if tool_calls:
            return tool_calls

        # Format 2: Bare JSON
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                data = json.loads(stripped)
                if self._is_valid_tool_call(data):
                    tool_calls.append(data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # Format 3: Trailing JSON with tool name
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                if self._is_valid_tool_call(data):
                    tool_calls.append(data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self.VALID_TOOL_NAMES:
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False

    def _get_tools_description(self) -> str:
        parts = ["可用工具："]
        for name, tool in self.tools.items():
            params_desc = ", ".join(f"{k}: {v}" for k, v in tool["parameters"].items())
            parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                parts.append(f"  参数: {params_desc}")
        return "\n".join(parts)

    # ── Outline Planning ──

    def plan_outline(self, progress_callback: Optional[Callable] = None) -> ReportOutline:
        logger.info(t('report.startPlanningOutline'))

        if progress_callback:
            progress_callback("planning", 0, t('progress.analyzingRequirements'))

        context = self.zep_tools.get_simulation_context(
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
        )

        if progress_callback:
            progress_callback("planning", 30, t('progress.generatingOutline'))

        # Get simulation analytics for the plan prompt
        analytics_overview = self.analytics.get_overview_stats(self.simulation_id)
        sentiment = self.analytics.get_sentiment_breakdown(self.simulation_id)

        system_prompt = f"{PLAN_SYSTEM_PROMPT}\n\n{get_language_instruction()}"
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            related_facts_json=json.dumps(context.get('related_facts', [])[:10], ensure_ascii=False, indent=2),
            total_rounds=analytics_overview.get('total_rounds', 0),
            total_agents=analytics_overview.get('total_agents', 0),
            twitter_posts=analytics_overview.get('twitter_posts', 0),
            reddit_posts=analytics_overview.get('reddit_posts', 0),
            total_engagement=analytics_overview.get('total_engagement', 0),
            positive_ratio=sentiment.get('positive_ratio', 0),
            negative_ratio=sentiment.get('negative_ratio', 0),
        )

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )

            if progress_callback:
                progress_callback("planning", 80, t('progress.parsingOutline'))

            sections = [
                ReportSection(title=s.get("title", ""), content="")
                for s in response.get("sections", [])
            ]
            outline = ReportOutline(
                title=response.get("title", "模拟分析报告"),
                summary=response.get("summary", ""),
                sections=sections,
            )

            if progress_callback:
                progress_callback("planning", 100, t('progress.outlinePlanComplete'))

            logger.info(t('report.outlinePlanDone', count=len(sections)))
            return outline

        except Exception as e:
            logger.error(t('report.outlinePlanFailed', error=str(e)))
            return ReportOutline(
                title="未来预测报告",
                summary="基于模拟预测的未来趋势与风险分析",
                sections=[
                    ReportSection(title="预测场景与核心发现"),
                    ReportSection(title="人群行为预测分析"),
                    ReportSection(title="趋势展望与风险提示"),
                ],
            )

    # ── Section Generation (ReACT) ──

    def _generate_section_react(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0,
    ) -> str:
        logger.info(t('report.reactGenerateSection', title=section.title))

        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)

        system_prompt = SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=section.title,
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        if previous_sections:
            parts = [sec[:4000] + "..." if len(sec) > 4000 else sec for sec in previous_sections]
            previous_content = "\n\n---\n\n".join(parts)
        else:
            previous_content = "（这是第一个章节）"

        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        tool_calls_count = 0
        max_iterations = 6
        min_tool_calls = 3
        conflict_retries = 0
        used_tools = set()
        all_tools = {"simulation_analytics", "insight_forge", "panorama_search", "quick_search", "interview_agents"}
        report_context = f"章节: {section.title}\n需求: {self.simulation_requirement}"

        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating",
                    int((iteration / max_iterations) * 100),
                    t('progress.deepSearchAndWrite', current=tool_calls_count, max=self.MAX_TOOL_CALLS_PER_SECTION),
                )

            response = self.llm.chat(
                messages=messages,
                temperature=0.5,
                max_tokens=8192,
            )

            if response is None:
                logger.warning(t('report.sectionIterNone', title=section.title, iteration=iteration + 1))
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "（响应为空）"})
                    messages.append({"role": "user", "content": "请继续生成内容。"})
                    continue
                break

            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # Conflict: both tool calls and Final Answer
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                if conflict_retries <= 2:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "【格式错误】你在一次回复中同时包含了工具调用和 Final Answer。\n"
                            "每次回复只能做一件事：调用工具 或 输出 Final Answer。请重新回复。"
                        ),
                    })
                    continue
                else:
                    first_end = response.find('edisnormal', response.find('edisnormal') + 10)
                    if first_end != -1:
                        response = response[:first_end + len('edisnormal')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            if self.report_logger:
                self.report_logger.log_llm_response(
                    section.title, section_index, response,
                    iteration + 1, has_tool_calls, has_final_answer,
                )

            # Case 1: Final Answer
            if has_final_answer:
                if tool_calls_count < min_tool_calls:
                    unused = all_tools - used_tools
                    hint = f"（推荐使用: {', '.join(unused)}）" if unused else ""
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=hint,
                        ),
                    })
                    continue

                final_answer = response.split("Final Answer:")[-1].strip()
                if self.report_logger:
                    self.report_logger.log_section_content(
                        section.title, section_index, final_answer, tool_calls_count,
                    )
                return final_answer

            # Case 2: Tool call
            if has_tool_calls:
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(t('report.multiToolOnlyFirst', total=len(tool_calls), toolName=call['name']))

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section.title, section_index, call["name"],
                        call.get("parameters", {}), iteration + 1,
                    )

                result = self._execute_tool(call["name"], call.get("parameters", {}), report_context)

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section.title, section_index, call["name"], result, iteration + 1,
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])

                unused = all_tools - used_tools
                unused_hint = ""
                if unused and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused))

                analytics_hint = ""
                if call["name"] == "simulation_analytics":
                    analytics_hint = "\n💡 simulation_analytics 返回了硬数据，请在 Final Answer 中引用具体数字！\n"

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                        analytics_hint=analytics_hint,
                    ),
                })
                continue

            # Case 3: Neither tool call nor Final Answer
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                unused = all_tools - used_tools
                hint = f"（推荐使用: {', '.join(unused)}）" if unused else ""
                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=hint,
                    ),
                })
                continue

            # Enough tools called, treat as final answer
            logger.info(t('report.sectionNoPrefix', title=section.title, count=tool_calls_count))
            final_answer = response.strip()
            if self.report_logger:
                self.report_logger.log_section_content(
                    section.title, section_index, final_answer, tool_calls_count,
                )
            return final_answer

        # Max iterations reached
        logger.warning(t('report.sectionMaxIter', title=section.title))
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})

        response = self.llm.chat(messages=messages, temperature=0.5, max_tokens=8192)

        if response is None:
            final_answer = t('report.sectionGenFailedContent')
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response

        if self.report_logger:
            self.report_logger.log_section_content(
                section.title, section_index, final_answer, tool_calls_count,
            )
        return final_answer

    # ── Full Report Generation ──

    def generate_report(
        self,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None,
    ) -> Report:
        import uuid

        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        start_time = time.time()

        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        )
        completed_section_titles = []

        try:
            ReportManager._ensure_report_folder(report_id)

            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                self.simulation_id, self.graph_id, self.simulation_requirement,
            )
            self.console_logger = ReportConsoleLogger(report_id)

            ReportManager.update_progress(report_id, "pending", 0, t('progress.initReport'), completed_sections=[])
            ReportManager.save_report(report)

            # Phase 1: Plan outline
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(report_id, "planning", 5, t('progress.startPlanningOutline'), completed_sections=[])

            self.report_logger.log_planning_start()

            if progress_callback:
                progress_callback("planning", 0, t('progress.startPlanningOutline'))

            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg:
                    progress_callback(stage, prog // 5, msg) if progress_callback else None,
            )
            report.outline = outline

            self.report_logger.log_planning_complete(outline.to_dict())
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15,
                t('progress.outlineDone', count=len(outline.sections)),
                completed_sections=[],
            )
            ReportManager.save_report(report)

            # Pre-compute infographic data
            try:
                infographic_data = self.analytics.get_infographic_data(self.simulation_id)
                ReportManager.save_infographic(report_id, infographic_data)
                logger.info(f"Infographic data saved for {report_id}")
            except Exception as e:
                logger.warning(f"Failed to pre-compute infographic: {e}")

            # Phase 2: Generate sections
            report.status = ReportStatus.GENERATING
            total_sections = len(outline.sections)
            generated_sections = []

            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)

                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    t('progress.generatingSection', title=section.title, current=section_num, total=total_sections),
                    current_section=section.title,
                    completed_sections=completed_section_titles,
                )

                if progress_callback:
                    progress_callback("generating", base_progress,
                                      t('progress.generatingSection', title=section.title, current=section_num, total=total_sections))

                section_content = self._generate_section_react(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=lambda stage, prog, msg:
                        progress_callback(stage, base_progress + int(prog * 0.7 / total_sections), msg)
                        if progress_callback else None,
                    section_index=section_num,
                )

                section.content = section_content
                generated_sections.append(f"## {section.title}\n\n{section_content}")
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                full_section = f"## {section.title}\n\n{section_content}"
                if self.report_logger:
                    self.report_logger.log_section_full_complete(section.title, section_num, full_section.strip())

                if section_num < total_sections:
                    time.sleep(3)

            # Phase 3: Assemble
            if progress_callback:
                progress_callback("generating", 95, t('progress.assemblingReport'))

            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = time.strftime('%Y-%m-%dT%H:%M:%S')

            total_time = time.time() - start_time
            if self.report_logger:
                self.report_logger.log_report_complete(total_sections, total_time)

            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, t('progress.reportComplete'),
                completed_sections=completed_section_titles,
            )

            if progress_callback:
                progress_callback("completed", 100, t('progress.reportComplete'))

            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report

        except Exception as e:
            logger.error(t('report.reportGenFailed', error=str(e)))
            report.status = ReportStatus.FAILED
            report.error = str(e)

            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")

            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1,
                    t('progress.reportFailed', error=str(e)),
                    completed_sections=completed_section_titles,
                )
            except Exception:
                pass

            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report

    # ── Chat ──

    def chat(self, message: str, chat_history: List[Dict[str, str]] = None) -> Dict[str, Any]:
        logger.info(t('report.agentChat', message=message[:50]))

        chat_history = chat_history or []

        report_content = ""
        try:
            report = ReportManager.get_report_by_simulation(self.simulation_id)
            if report and report.markdown_content:
                report_content = report.markdown_content[:15000]
                if len(report.markdown_content) > 15000:
                    report_content += "\n\n... [报告内容已截断] ..."
        except Exception as e:
            logger.warning(t('report.fetchReportFailed', error=e))

        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "（暂无报告）",
            tools_description=self._get_tools_description(),
        )
        system_prompt = f"{system_prompt}\n\n{get_language_instruction()}"

        messages = [{"role": "system", "content": system_prompt}]
        for h in chat_history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": message})

        tool_calls_made = []
        max_iterations = 2

        for iteration in range(max_iterations):
            response = self.llm.chat(messages=messages, temperature=0.5)

            tool_calls = self._parse_tool_calls(response)

            if not tool_calls:
                clean = re.sub(r'edisnormal.*?edisnormal', '', response, flags=re.DOTALL)
                return {
                    "response": clean.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made],
                }

            tool_results = []
            for call in tool_calls[:1]:
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({"tool": call["name"], "result": result[:1500]})
                tool_calls_made.append(call)

            messages.append({"role": "assistant", "content": response})
            observation = "\n".join(f"[{r['tool']}结果]\n{r['result']}" for r in tool_results)
            messages.append({"role": "user", "content": observation + CHAT_OBSERVATION_SUFFIX})

        final_response = self.llm.chat(messages=messages, temperature=0.5)
        clean = re.sub(r'edisnormal.*?edisnormal', '', final_response, flags=re.DOTALL)
        return {
            "response": clean.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made],
        }
