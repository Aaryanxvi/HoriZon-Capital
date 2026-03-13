"""Google Gemini LLM provider."""

from __future__ import annotations

from app.llm.base_provider import BaseLLMProvider


class GeminiProvider(BaseLLMProvider):
    """Wraps the Google Generative AI API (Gemini)."""

    provider_name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        super().__init__(api_key)
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._client = genai.GenerativeModel(self.model)
        return self._client

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> str:
        client = self._get_client()
        # Build conversation: system prompt + messages
        prompt_parts = [f"System: {system_prompt}\n"]
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prompt_parts.append(f"{role.capitalize()}: {content}")

        import asyncio
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.generate_content(
                "\n".join(prompt_parts),
                generation_config={"temperature": temperature, "max_output_tokens": 4096},
            ),
        )
        return response.text

    async def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False
