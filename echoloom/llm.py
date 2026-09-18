"""智谱 GLM 客户端（stdlib urllib）+ 重试。

文档: https://open.bigmodel.cn/dev/api  POST /api/paas/v4/chat/completions
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .prompts import parse_json_response

ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


class LLMError(RuntimeError):
    pass


class ZhipuClient:
    def __init__(self, api_key: str, model: str = "glm-4.6", timeout: int = 300,
                 max_retries: int = 5):
        if not api_key:
            raise LLMError("缺少 ZHIPUAI_API_KEY（.env 或环境变量）")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.8,
             thinking: str = "disabled") -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "thinking": {"type": thinking},
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return self._once(body)
            except LLMTransientError as e:
                last_err = e
                time.sleep(min(2.0 * (2 ** attempt), 30.0))
        raise LLMError(f"LLM 重试 {self.max_retries} 次仍失败: {last_err}")

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.7) -> Any:
        return parse_json_response(self.chat(messages, temperature=temperature))

    def _once(self, body: dict) -> str:
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504):
                raise LLMTransientError(f"HTTP {e.code}: {detail}") from e
            raise LLMError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise LLMTransientError(f"网络错误: {e}") from e
        try:
            content = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"响应结构异常: {json.dumps(resp, ensure_ascii=False)[:300]}") from e
        if not content:
            raise LLMError("LLM 返回空内容")
        return content


class LLMTransientError(Exception):
    """可重试的瞬时错误（429/5xx/网络）。"""
