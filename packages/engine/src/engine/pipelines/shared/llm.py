"""LLM 客户端（AsyncOpenAI，pipeline 通用），凭证来自平台 settings / 环境变量。

密钥通过 backend Settings（.env: LLM_API_KEY / LLM_BASE_URL）注入；
模型名由调用方按业务解析（config 覆盖 > settings/env，经 llm.setting() 取值）；
config 可用 temperature / max_tokens / enable_thinking / retry_max 覆盖采样与重试。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from openai import AsyncOpenAI


class LlmClient:
    """OpenAI 兼容客户端 + JSON 模式请求 + 指数退避重试。"""

    def __init__(self, settings: Any, config: dict) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=self.setting("llm_api_key"),
            base_url=self.setting("llm_base_url"),
        )
        self._max_retries = config.get("retry_max", 2)
        self._enable_thinking = config.get("enable_thinking", False)
        self.temperature = config.get("temperature", 0.2)
        self.max_tokens = config.get("max_tokens", 16384)

    def setting(self, name: str) -> str:
        """优先平台 settings，其次环境变量（直连测试兜底）。"""
        return getattr(self._settings, name, None) or os.environ.get(name.upper(), "")

    async def close(self) -> None:
        await self._client.close()

    async def _with_retry(self, coro_fn, label: str, log) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await coro_fn()
            except Exception as e:
                last_exc = e
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    await log.warn(
                        "llm", f"{label} 重试 {attempt + 1}/{self._max_retries}: {e}"
                    )
                    await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    async def _chat(self, system_prompt: str, user_content: str, model: str) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            extra_body={} if self._enable_thinking else {"enable_thinking": False},
        )
        return response.choices[0].message.content or ""

    async def ask_json(
        self,
        system_prompt: str,
        user_content: str,
        model: str,
        log,
        label: str = "LLM",
    ) -> dict[str, Any]:
        """JSON 模式请求，返回解析后的 dict；模型由调用方按业务指定。"""
        text = await self._with_retry(
            lambda: self._chat(system_prompt, user_content, model), label, log,
        )
        return json.loads(text)
