"""
Token 用量追踪器（v0.3 新增）

进程内全局单例，按 stage 维度统计 LLM token 消耗。
- LLMClient 自动 record 每次 API call 的 prompt/completion tokens
- 调用方在 stage 切换时 set_stage("step1_ontology")
- 通过 GET /api/usage/summary 查询
- 用于成本估算和销售定价

说明：
1. 这是 Flask 后端进程内的统计，不包含 OASIS 模拟子进程的 LLM 消耗
   (camel-ai 用自己的 LLM client，需另外估算)
2. 进程重启会丢失数据，如需持久化可用 reset() 前先 dump 到文件
3. 价格为每 1K tokens 的 CNY 价格，参考各 provider 官网 (2026-04 价格)
"""

import threading
from typing import Optional, Dict, Any

_lock = threading.Lock()

# 全局状态：{stage: {model: {prompt_tokens, completion_tokens, calls}}}
_stage_usage: Dict[str, Dict[str, Dict[str, int]]] = {}
_current_stage: Optional[str] = None

# 模型定价表（CNY per 1K tokens, prompt / completion）
# 来源：各 provider 2026-04 官网价格
PRICING = {
    # 智谱 GLM 系列
    "glm-4-flash": {"prompt": 0.0001, "completion": 0.0001},
    "glm-4-flashx": {"prompt": 0.001, "completion": 0.001},
    "glm-4-air": {"prompt": 0.001, "completion": 0.001},
    "glm-4-plus": {"prompt": 0.05, "completion": 0.05},
    "glm-4.6": {"prompt": 0.05, "completion": 0.05},
    "glm-5.1": {"prompt": 0.1, "completion": 0.1},
    # SiliconFlow 免费
    "qwen/qwen2.5-32b-instruct": {"prompt": 0.0, "completion": 0.0},
    "qwen2.5-32b-instruct": {"prompt": 0.0, "completion": 0.0},
    "baai/bge-m3": {"prompt": 0.0, "completion": 0.0},
    # MiniMax
    "minimax-m2.7-highspeed": {"prompt": 0.001, "completion": 0.001},
    "minimax-m2.5": {"prompt": 0.001, "completion": 0.002},
    # Anthropic / OpenAI（备用）
    "gpt-4o-mini": {"prompt": 0.0011, "completion": 0.0044},
    "gpt-4o": {"prompt": 0.018, "completion": 0.072},
    "claude-haiku-4-5": {"prompt": 0.0072, "completion": 0.036},
    "claude-sonnet-4-6": {"prompt": 0.022, "completion": 0.108},
    # 兜底
    "default": {"prompt": 0.001, "completion": 0.002},
}


def _get_pricing(model: str) -> Dict[str, float]:
    if not model:
        return PRICING["default"]
    key = model.lower().strip()
    if key in PRICING:
        return PRICING[key]
    # 模糊匹配（去掉版本号）
    for k in PRICING:
        if k != "default" and (key.startswith(k) or k.startswith(key)):
            return PRICING[k]
    return PRICING["default"]


def set_stage(name: Optional[str]) -> None:
    """设置当前 stage 名称，后续的 LLM 调用会归到这个 stage 下"""
    global _current_stage
    with _lock:
        _current_stage = name


def get_stage() -> Optional[str]:
    return _current_stage


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    stage: Optional[str] = None,
) -> None:
    """记录一次 LLM 调用的 token 消耗"""
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        return
    s = stage or _current_stage or "unknown"
    with _lock:
        stage_bucket = _stage_usage.setdefault(s, {})
        model_bucket = stage_bucket.setdefault(
            model or "unknown",
            {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
        )
        model_bucket["prompt_tokens"] += prompt_tokens
        model_bucket["completion_tokens"] += completion_tokens
        model_bucket["calls"] += 1


def get_summary() -> Dict[str, Any]:
    """
    返回当前累计的 token 用量与估算成本。

    格式：
    {
        "stages": {
            "step1_ontology": {
                "by_model": {"glm-4-flash": {"prompt_tokens": 1234, "completion_tokens": 567, "calls": 3, "estimated_cost_cny": 0.0002}},
                "prompt_tokens": 1234,
                "completion_tokens": 567,
                "calls": 3,
                "estimated_cost_cny": 0.0002
            },
            ...
        },
        "total": {
            "prompt_tokens": 50000,
            "completion_tokens": 12000,
            "calls": 45,
            "estimated_cost_cny": 0.0123
        }
    }
    """
    with _lock:
        stages_out = {}
        total_prompt = 0
        total_completion = 0
        total_calls = 0
        total_cost = 0.0

        for stage_name, models in _stage_usage.items():
            stage_data = {
                "by_model": {},
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "calls": 0,
                "estimated_cost_cny": 0.0,
            }
            for model_name, m in models.items():
                pricing = _get_pricing(model_name)
                cost = (
                    m["prompt_tokens"] / 1000.0 * pricing["prompt"]
                    + m["completion_tokens"] / 1000.0 * pricing["completion"]
                )
                stage_data["by_model"][model_name] = {
                    "prompt_tokens": m["prompt_tokens"],
                    "completion_tokens": m["completion_tokens"],
                    "calls": m["calls"],
                    "estimated_cost_cny": round(cost, 6),
                }
                stage_data["prompt_tokens"] += m["prompt_tokens"]
                stage_data["completion_tokens"] += m["completion_tokens"]
                stage_data["calls"] += m["calls"]
                stage_data["estimated_cost_cny"] += cost

            stage_data["estimated_cost_cny"] = round(stage_data["estimated_cost_cny"], 6)
            stages_out[stage_name] = stage_data
            total_prompt += stage_data["prompt_tokens"]
            total_completion += stage_data["completion_tokens"]
            total_calls += stage_data["calls"]
            total_cost += stage_data["estimated_cost_cny"]

        return {
            "stages": stages_out,
            "total": {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "calls": total_calls,
                "estimated_cost_cny": round(total_cost, 6),
            },
            "current_stage": _current_stage,
        }


def reset(stage: Optional[str] = None) -> None:
    """清空统计。stage=None 全部清空，否则只清空指定 stage"""
    global _stage_usage
    with _lock:
        if stage is None:
            _stage_usage = {}
        else:
            _stage_usage.pop(stage, None)


def estimate_simulation_cost(
    rounds: int,
    active_agents_per_round_avg: int,
    llm_calls_per_action: int = 4,
    avg_prompt_tokens_per_call: int = 800,
    avg_completion_tokens_per_call: int = 200,
    model: str = "glm-4-flash",
) -> Dict[str, Any]:
    """
    估算 OASIS 模拟子进程的 token 消耗（无法精确测，只能估算）

    OASIS 内部每个 agent action 通常需要 3-5 次 LLM 调用：
    1. 读 timeline / 推荐过滤
    2. 决策（要做什么动作）
    3. 生成内容
    4. 偶尔 reflection

    Args:
        rounds: 模拟轮数
        active_agents_per_round_avg: 每轮平均激活的 agent 数
        llm_calls_per_action: 每个 action 内部 LLM 调用次数（默认 4）
        avg_prompt_tokens_per_call: 平均 prompt token
        avg_completion_tokens_per_call: 平均 completion token
        model: 模型名（用于查询定价）

    Returns:
        估算结果含 token / 成本范围（low/mid/high）
    """
    total_actions = rounds * active_agents_per_round_avg
    total_calls = total_actions * llm_calls_per_action

    pricing = _get_pricing(model)

    mid_prompt = total_calls * avg_prompt_tokens_per_call
    mid_completion = total_calls * avg_completion_tokens_per_call
    mid_cost = (
        mid_prompt / 1000.0 * pricing["prompt"]
        + mid_completion / 1000.0 * pricing["completion"]
    )

    return {
        "model": model,
        "rounds": rounds,
        "active_agents_per_round_avg": active_agents_per_round_avg,
        "llm_calls_per_action": llm_calls_per_action,
        "total_actions": total_actions,
        "total_llm_calls": total_calls,
        "estimated_prompt_tokens": mid_prompt,
        "estimated_completion_tokens": mid_completion,
        "estimated_cost_cny": {
            "low": round(mid_cost * 0.6, 4),
            "mid": round(mid_cost, 4),
            "high": round(mid_cost * 1.6, 4),
        },
        "note": "这是估算值，OASIS 模拟在子进程中运行，无法精确追踪。实际值可能在 low-high 区间内浮动。",
    }
