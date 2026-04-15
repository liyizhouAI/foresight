"""
Token 用量查询 API（v0.3 新增）

提供 LLM token 消耗的实时统计与成本估算。
内部用途，销售给客户的版本可移除此 blueprint 注册。
"""

from flask import jsonify, request
from . import usage_bp
from ..utils import token_tracker
from ..utils.logger import get_logger

logger = get_logger('foresight.api.usage')


@usage_bp.route('/summary', methods=['GET'])
def get_usage_summary():
    """
    获取当前累计 token 用量摘要

    返回：
        {
            "success": true,
            "data": {
                "stages": {
                    "<stage_name>": {
                        "by_model": {...},
                        "prompt_tokens": int,
                        "completion_tokens": int,
                        "calls": int,
                        "estimated_cost_cny": float
                    }
                },
                "total": {...},
                "current_stage": "..."
            }
        }
    """
    try:
        return jsonify({
            "success": True,
            "data": token_tracker.get_summary(),
        })
    except Exception as e:
        logger.error(f"获取 token 用量失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@usage_bp.route('/reset', methods=['POST'])
def reset_usage():
    """
    清空 token 用量统计

    Body (可选):
        {"stage": "<stage_name>"}  // 不填则全部清空
    """
    try:
        data = request.get_json(silent=True) or {}
        stage = data.get("stage")
        token_tracker.reset(stage)
        return jsonify({
            "success": True,
            "data": {"reset_stage": stage or "all"},
        })
    except Exception as e:
        logger.error(f"重置 token 用量失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@usage_bp.route('/estimate-simulation', methods=['GET'])
def estimate_simulation():
    """
    估算 OASIS 模拟子进程的 token 消耗（无法精确追踪，只能估算）

    Query params:
        rounds: 模拟轮数 (默认 15)
        active_agents_per_round: 每轮平均激活 agent 数 (默认 10)
        llm_calls_per_action: 每动作 LLM 调用次数 (默认 4)
        prompt_tokens: 平均 prompt token (默认 800)
        completion_tokens: 平均 completion token (默认 200)
        model: 模型名 (默认 glm-4-flash)
    """
    try:
        rounds = request.args.get('rounds', 15, type=int)
        agents = request.args.get('active_agents_per_round', 10, type=int)
        calls = request.args.get('llm_calls_per_action', 4, type=int)
        prompt = request.args.get('prompt_tokens', 800, type=int)
        completion = request.args.get('completion_tokens', 200, type=int)
        model = request.args.get('model', 'glm-4-flash')

        result = token_tracker.estimate_simulation_cost(
            rounds=rounds,
            active_agents_per_round_avg=agents,
            llm_calls_per_action=calls,
            avg_prompt_tokens_per_call=prompt,
            avg_completion_tokens_per_call=completion,
            model=model,
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"估算模拟 token 失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@usage_bp.route('/set-stage', methods=['POST'])
def set_stage():
    """
    手动设置当前 stage（用于测试或非自动埋点的场景）

    Body: {"stage": "<stage_name>"}
    """
    try:
        data = request.get_json(silent=True) or {}
        stage = data.get("stage")
        token_tracker.set_stage(stage)
        return jsonify({"success": True, "data": {"current_stage": stage}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
