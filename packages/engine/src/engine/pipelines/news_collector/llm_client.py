"""LLM 调用封装 — 基于 litellm 统一接口。

环境变量:
  LLM_API_KEY:   API 密钥（必填）
  LLM_MODEL:     模型名（默认 gpt-4o）
  LLM_BASE_URL:  API base URL（可选，用于自建/代理）
"""

from __future__ import annotations

import json
import os
import re

import litellm


async def _acompletion(messages: list[dict], **kwargs):
    """内部包装，方便测试 mock。"""
    model = os.environ.get("LLM_MODEL", "gpt-4o")
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL")
    kw = {"model": model, "messages": messages, "api_key": api_key}
    if base_url:
        kw["api_base"] = base_url
    kw.update(kwargs)
    return await litellm.acompletion(**kw)


async def call_llm(prompt: str, system: str | None = None) -> str:
    """调用 LLM，返回原始文本。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = await _acompletion(messages)
    return response.choices[0].message.content


async def call_llm_json(prompt: str, system: str | None = None) -> dict:
    """调用 LLM，解析返回 JSON。自动去除 markdown 代码块包裹。"""
    text = await call_llm(prompt, system)
    # 去除 ```json ... ``` 包裹
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text)
