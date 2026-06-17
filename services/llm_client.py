from __future__ import annotations

import json
import re
from typing import Any

import httpx

from config.settings import AgentModelConfig

_MARKDOWN_JSON_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _extract_json_from_text(text: str) -> str:
    """Strip markdown code fences from LLM output, returning raw JSON text."""
    match = _MARKDOWN_JSON_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


class OpenAICompatibleLlmClient:
    """Small OpenAI-compatible chat client used by optional agent enhancements."""

    # ------------------------------------------------------------------
    # generic JSON-mode chat
    # ------------------------------------------------------------------

    def chat_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call an OpenAI-compatible chat API and return structured JSON.

        Returns a dict with keys ``content`` (parsed JSON), ``token_usage``,
        and ``model``.

        Raises :exc:`ValueError` when *config.api_key* or *config.base_url*
        is missing, and :exc:`json.JSONDecodeError` when the response cannot
        be parsed as JSON.
        """
        if not config.api_key:
            raise ValueError(f"agent {config.agent_name} api key is not configured")
        if not config.base_url:
            raise ValueError(f"agent {config.agent_name} base url is not configured")

        effective_system = (
            system_prompt
            + "\n\n请严格按照 JSON 格式输出，不要包含任何解释文字。"
        )

        request_body: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": effective_system},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature if temperature is not None else config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else config.max_tokens,
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

        raw_text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        cleaned = _extract_json_from_text(raw_text)
        parsed = json.loads(cleaned)

        usage = data.get("usage", {})
        token_usage = {
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

        return {
            "content": parsed,
            "token_usage": token_usage,
            "model": config.model,
        }

    # ------------------------------------------------------------------
    # legacy exception analyzer (backward-compatible)
    # ------------------------------------------------------------------

    def analyze_exception(
        self,
        config: AgentModelConfig,
        snapshot: dict[str, Any],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Legacy wrapper — delegates to :meth:`chat_json`."""
        system_prompt = (
            "你是检测队列仿真系统的异常分析 Agent。"
            "只基于输入快照解释阻塞、延期和瓶颈，不虚构真实检测中心数据。"
        )
        user_message = json.dumps(
            {"snapshot": snapshot, "payload": payload or {}},
            ensure_ascii=False,
        )
        try:
            result = self.chat_json(config, system_prompt, user_message)
        except (json.JSONDecodeError, ValueError):
            raise
        return {
            "mode": "llm",
            "model": result["model"],
            "content": json.dumps(result["content"], ensure_ascii=False),
            "token_usage": result["token_usage"],
        }
