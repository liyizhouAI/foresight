"""
Report 数据类、日志记录器和报告管理器

从 report_agent.py 中提取，包含：
- ReportStatus, ReportSection, ReportOutline, Report 数据类
- ReportLogger (结构化 agent_log.jsonl)
- ReportConsoleLogger (控制台 console_log.txt)
- ReportManager (文件持久化)
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ..config import Config
from ..utils.logger import get_logger
from ..utils.locale import t

logger = get_logger('foresight.report_data')


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

class ReportStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    title: str
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"title": self.title, "content": self.content}

    def to_markdown(self, level: int = 2) -> str:
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    title: str
    summary: str
    sections: List[ReportSection]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections],
        }

    def to_markdown(self) -> str:
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════
# ReportLogger — 结构化 agent_log.jsonl
# ═══════════════════════════════════════════════════════════════

class ReportLogger:
    def __init__(self, report_id: str):
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        self._ensure_log_file()

    def _ensure_log_file(self):
        os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)

    def _elapsed(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    def log(self, action: str, stage: str, details: Dict[str, Any],
            section_title: str = None, section_index: int = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._elapsed(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details,
        }
        with open(self.log_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        self.log("report_start", "pending", {
            "simulation_id": simulation_id,
            "graph_id": graph_id,
            "simulation_requirement": simulation_requirement,
            "message": t('report.taskStarted'),
        })

    def log_planning_start(self):
        self.log("planning_start", "planning", {"message": t('report.planningStart')})

    def log_planning_context(self, context: Dict[str, Any]):
        self.log("planning_context", "planning", {
            "message": t('report.fetchSimContext'),
            "context": context,
        })

    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        self.log("planning_complete", "planning", {
            "message": t('report.planningComplete'),
            "outline": outline_dict,
        })

    def log_section_start(self, section_title: str, section_index: int):
        self.log("section_start", "generating",
                 {"message": t('report.sectionStart', title=section_title)},
                 section_title=section_title, section_index=section_index)

    def log_react_thought(self, section_title: str, section_index: int,
                          iteration: int, thought: str):
        self.log("react_thought", "generating", {
            "iteration": iteration, "thought": thought,
            "message": t('report.reactThought', iteration=iteration),
        }, section_title=section_title, section_index=section_index)

    def log_tool_call(self, section_title: str, section_index: int,
                      tool_name: str, parameters: Dict[str, Any], iteration: int):
        self.log("tool_call", "generating", {
            "iteration": iteration, "tool_name": tool_name, "parameters": parameters,
            "message": t('report.toolCall', toolName=tool_name),
        }, section_title=section_title, section_index=section_index)

    def log_tool_result(self, section_title: str, section_index: int,
                        tool_name: str, result: str, iteration: int):
        self.log("tool_result", "generating", {
            "iteration": iteration, "tool_name": tool_name,
            "result": result, "result_length": len(result),
            "message": t('report.toolResult', toolName=tool_name),
        }, section_title=section_title, section_index=section_index)

    def log_llm_response(self, section_title: str, section_index: int,
                         response: str, iteration: int,
                         has_tool_calls: bool, has_final_answer: bool):
        self.log("llm_response", "generating", {
            "iteration": iteration, "response": response,
            "response_length": len(response),
            "has_tool_calls": has_tool_calls, "has_final_answer": has_final_answer,
            "message": t('report.llmResponse', hasToolCalls=has_tool_calls,
                         hasFinalAnswer=has_final_answer),
        }, section_title=section_title, section_index=section_index)

    def log_section_content(self, section_title: str, section_index: int,
                            content: str, tool_calls_count: int):
        self.log("section_content", "generating", {
            "content": content, "content_length": len(content),
            "tool_calls_count": tool_calls_count,
            "message": t('report.sectionContentDone', title=section_title),
        }, section_title=section_title, section_index=section_index)

    def log_section_full_complete(self, section_title: str, section_index: int,
                                  full_content: str):
        self.log("section_complete", "generating", {
            "content": full_content, "content_length": len(full_content),
            "message": t('report.sectionComplete', title=section_title),
        }, section_title=section_title, section_index=section_index)

    def log_report_complete(self, total_sections: int, total_time_seconds: float):
        self.log("report_complete", "completed", {
            "total_sections": total_sections,
            "total_time_seconds": round(total_time_seconds, 2),
            "message": t('report.reportComplete'),
        })

    def log_error(self, error_message: str, stage: str, section_title: str = None):
        self.log("error", stage, {
            "error": error_message,
            "message": t('report.errorOccurred', error=error_message),
        }, section_title=section_title)


# ═══════════════════════════════════════════════════════════════
# ReportConsoleLogger — console_log.txt
# ═══════════════════════════════════════════════════════════════

class ReportConsoleLogger:
    def __init__(self, report_id: str):
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        self._setup_file_handler()

    def _ensure_log_file(self):
        os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)

    def _setup_file_handler(self):
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s', datefmt='%H:%M:%S'
        )
        self._file_handler = logging.FileHandler(
            self.log_file_path, mode='a', encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)
        self._file_handler.setFormatter(formatter)

        for name in ('foresight.report_agent', 'foresight.zep_tools'):
            target = logging.getLogger(name)
            if self._file_handler not in target.handlers:
                target.addHandler(self._file_handler)

    def close(self):
        if not self._file_handler:
            return
        for name in ('foresight.report_agent', 'foresight.zep_tools'):
            target = logging.getLogger(name)
            if self._file_handler in target.handlers:
                target.removeHandler(self._file_handler)
        self._file_handler.close()
        self._file_handler = None

    def __del__(self):
        self.close()


# ═══════════════════════════════════════════════════════════════
# ReportManager — 文件持久化
# ═══════════════════════════════════════════════════════════════

class ReportManager:
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')

    @classmethod
    def _ensure_reports_dir(cls):
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)

    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        return os.path.join(cls.REPORTS_DIR, report_id)

    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder

    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "meta.json")

    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")

    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "outline.json")

    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "progress.json")

    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")

    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")

    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")

    # ── Infographic ──

    @classmethod
    def _get_infographic_path(cls, report_id: str) -> str:
        return os.path.join(cls._get_report_folder(report_id), "infographic_data.json")

    @classmethod
    def save_infographic(cls, report_id: str, data: Dict[str, Any]) -> None:
        path = cls._get_infographic_path(report_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def get_infographic(cls, report_id: str) -> Optional[Dict[str, Any]]:
        path = cls._get_infographic_path(report_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    # ── Console Log ──

    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        log_path = cls._get_console_log_path(report_id)
        if not os.path.exists(log_path):
            return {"logs": [], "total_lines": 0, "from_line": 0, "has_more": False}

        logs = []
        total_lines = 0
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    logs.append(line.rstrip('\n\r'))

        return {"logs": logs, "total_lines": total_lines, "from_line": from_line, "has_more": False}

    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        return cls.get_console_log(report_id, from_line=0)["logs"]

    # ── Agent Log ──

    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        log_path = cls._get_agent_log_path(report_id)
        if not os.path.exists(log_path):
            return {"logs": [], "total_lines": 0, "from_line": 0, "has_more": False}

        logs = []
        total_lines = 0
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        logs.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue

        return {"logs": logs, "total_lines": total_lines, "from_line": from_line, "has_more": False}

    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        return cls.get_agent_log(report_id, from_line=0)["logs"]

    # ── Outline ──

    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        path = cls._get_outline_path(report_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(outline.to_dict(), f, ensure_ascii=False, indent=2)

    # ── Section ──

    @classmethod
    def save_section(cls, report_id: str, section_index: int, section: ReportSection) -> None:
        path = cls._get_section_path(report_id, section_index)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"## {section.title}\n\n{section.content}")

    # ── Progress ──

    @classmethod
    def update_progress(cls, report_id: str, status: str, progress: int,
                        message: str, **kwargs) -> None:
        path = cls._get_progress_path(report_id)
        data = {"status": status, "progress": progress, "message": message}
        data.update(kwargs)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Full Report ──

    @classmethod
    def save_report(cls, report: Report) -> None:
        cls._ensure_report_folder(report.report_id)
        path = cls._get_report_path(report.report_id)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        path = cls._get_report_path(report_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        outline = None
        if data.get('outline'):
            sections = [ReportSection(**s) for s in data['outline'].get('sections', [])]
            outline = ReportOutline(
                title=data['outline']['title'],
                summary=data['outline']['summary'],
                sections=sections,
            )

        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=data.get('markdown_content', ''),
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error'),
        )

    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        cls._ensure_reports_dir()
        for name in sorted(os.listdir(cls.REPORTS_DIR), reverse=True):
            meta_path = os.path.join(cls.REPORTS_DIR, name, "meta.json")
            if not os.path.exists(meta_path):
                continue
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('simulation_id') == simulation_id and data.get('status') == 'completed':
                    return cls.get_report(name)
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        md = f"# {outline.title}\n\n"
        md += f"> {outline.summary}\n\n"
        for i, section in enumerate(outline.sections, 1):
            section_path = cls._get_section_path(report_id, i)
            if os.path.exists(section_path):
                with open(section_path, 'r', encoding='utf-8') as f:
                    md += f.read() + "\n\n"
            else:
                md += f"## {section.title}\n\n{section.content}\n\n"
        return md
