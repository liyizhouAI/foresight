"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
import time
import random
import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI, RateLimitError, APIError, APIConnectionError, APITimeoutError

from ..config import Config

logger = logging.getLogger('foresight.llm_client')

# 重试配置（针对 429 / 5xx / 超时 / 连接错误）
_MAX_RETRIES = 5
_BASE_BACKOFF = 1.0  # 首次重试等 1s
_MAX_BACKOFF = 30.0  # 单次最多等 30s


def _is_rate_limit_error(err: Exception) -> bool:
    """判断是否是速率限制/可重试错误"""
    if isinstance(err, (RateLimitError, APIConnectionError, APITimeoutError)):
        return True
    if isinstance(err, APIError):
        # 429 / 500 / 502 / 503 / 504 都可重试
        status = getattr(err, "status_code", None) or getattr(err, "code", None)
        try:
            status = int(status) if status else None
        except (ValueError, TypeError):
            status = None
        if status in (429, 500, 502, 503, 504):
            return True
        # 智谱 1302 = 速率限制
        msg = str(err)
        if "1302" in msg or "rate limit" in msg.lower() or "速率限制" in msg or "too many request" in msg.lower():
            return True
    return False


class LLMClient:
    """LLM客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）
            
        Returns:
            模型响应文本
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            kwargs["response_format"] = response_format

        # 带指数退避的重试：处理 429/5xx/超时等可恢复错误
        response = None
        last_err = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except Exception as err:
                last_err = err
                if attempt >= _MAX_RETRIES or not _is_rate_limit_error(err):
                    raise
                # 指数退避 + 随机抖动
                backoff = min(_MAX_BACKOFF, _BASE_BACKOFF * (2 ** attempt))
                backoff += random.uniform(0, backoff * 0.3)
                logger.warning(
                    f"LLM 调用遇到可重试错误 (attempt {attempt + 1}/{_MAX_RETRIES}): "
                    f"{type(err).__name__}: {str(err)[:200]}. 退避 {backoff:.1f}s 后重试..."
                )
                time.sleep(backoff)
        if response is None:
            raise last_err or RuntimeError("LLM 调用失败（未知原因）")

        # Token 追踪（v0.3 新增）：记录每次调用的 token 消耗，按当前 stage 归类
        try:
            from . import token_tracker
            usage = getattr(response, "usage", None)
            if usage is not None:
                token_tracker.record_usage(
                    model=self.model,
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
        except Exception:
            pass  # 永不阻塞主流程

        content = response.choices[0].message.content
        # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")

