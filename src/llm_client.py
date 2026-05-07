import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
import time as _time

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 512
    timeout: float = 10.0
    max_retries: int = 2


class LLMClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()

        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY", "")
        base_url = self.config.base_url or os.environ.get("OPENAI_BASE_URL", None)

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.config.timeout,
        )

    async def chat(
        self,
        messages: list[dict],
        json_output: bool = False,
        temperature: float | None = None,
    ) -> str:
        """Call LLM with fallback retry on failure."""
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": temperature or self.config.temperature,
        }
        if json_output:
            kwargs["response_format"] = {"type": "json_object"}

        t0 = _time.time()
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = await self.client.chat.completions.create(**kwargs)
                elapsed_ms = (_time.time() - t0) * 1000
                try:
                    from metrics import get_metrics
                    get_metrics().record_latency("llm_chat", elapsed_ms)
                except ImportError:
                    pass
                content = resp.choices[0].message.content
                if content is None:
                    raise ValueError("LLM returned empty content")
                if json_output:
                    json.loads(content)  # validate JSON
                return content
            except json.JSONDecodeError:
                logger.warning("LLM returned invalid JSON, retry %d", attempt + 1)
                if attempt < self.config.max_retries:
                    kwargs["messages"].append({
                        "role": "system",
                        "content": "你上次返回的内容不是合法JSON，请严格返回JSON格式。",
                    })
                    continue
                return json.dumps({"response": "...", "action": "idle"}, ensure_ascii=False)
            except Exception as e:
                logger.warning("LLM call failed (%s), retry %d", type(e).__name__, attempt + 1)
                if attempt < self.config.max_retries:
                    await asyncio.sleep(1)
                    continue
                return self._fallback_response()

        return self._fallback_response()

    @staticmethod
    def _fallback_response() -> str:
        """Rule-based fallback when LLM is unavailable."""
        return json.dumps({
            "response": "...（沉默）",
            "action": "idle",
            "emotion": "neutral",
            "target": None,
        }, ensure_ascii=False)


# Singleton for easy import
_default_client: LLMClient | None = None


def get_llm_client(config: LLMConfig | None = None) -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient(config)
    return _default_client
