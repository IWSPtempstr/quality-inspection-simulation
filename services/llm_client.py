from __future__ import annotations

import json
from typing import Any

import httpx

from config.settings import AgentModelConfig


class OpenAICompatibleLlmClient:
    """Small OpenAI-compatible chat client used by optional agent enhancements."""

    def analyze_exception(
        self,
        config: AgentModelConfig,
        snapshot: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not config.api_key:
            raise ValueError("exception analyzer api key is not configured")
        if not config.base_url:
            raise ValueError("exception analyzer base url is not configured")

        request_body = {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是检测队列仿真系统的异常分析 Agent。"
                        "只基于输入快照解释阻塞、延期和瓶颈，不虚构真实检测中心数据。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"snapshot": snapshot, "payload": payload or {}},
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if "qwen" in config.model.lower():
            request_body["enable_thinking"] = config.enable_thinking

        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
        with httpx.Client(timeout=30) as client:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {config.api_key}"},
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return {
            "mode": "llm",
            "model": config.model,
            "content": content,
        }
