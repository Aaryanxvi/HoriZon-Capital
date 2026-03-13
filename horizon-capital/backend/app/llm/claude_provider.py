"""Anthropic Claude LLM provider."""

from __future__ import annotations

from app.llm.base_provider import BaseLLMProvider


class ClaudeProvider(BaseLLMProvider):
    """Wraps the Anthropic Messages API."""

    provider_name = "claude"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        super().__init__(api_key)
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        client = self._get_client()
        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            temperature=temperature,
        )
        return response.content[0].text

    async def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False
