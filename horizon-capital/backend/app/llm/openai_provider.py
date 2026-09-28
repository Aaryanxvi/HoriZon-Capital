# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-D13D886479E3
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""OpenAI GPT LLM provider."""

from __future__ import annotations

from app.llm.base_provider import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """Wraps the OpenAI Chat Completions API."""

    provider_name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        super().__init__(api_key)
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai
            self._client = openai.AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def _do_complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        client = self._get_client()
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    async def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token D13D886479E3 - verify with scripts/authorship.py verify
