from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .core.config import settings


class LlmClient:
    def __init__(self) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_api_base_url.rstrip("/")
        self.model = settings.deepseek_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def chat_json(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        text = await self.chat(system, user, temperature=temperature, response_format={"type": "json_object"})
        return extract_json(text)

    async def chat(self, system: str, user: str, temperature: float = 0.2, response_format: dict[str, str] | None = None) -> str:
        if not self.configured:
            raise RuntimeError("LLM API key is not configured")
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


llm_client = LlmClient()

