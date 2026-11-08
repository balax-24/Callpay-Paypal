"""LLM providers: Claude -> OpenAI -> Gemini -> Ollama (local)."""

from dataclasses import dataclass

import httpx

from ..config import Settings
from .chain import FallbackChain


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


class LLMProvider:
    name = "base"

    def __init__(self, s: Settings, client: httpx.AsyncClient):
        self.s = s
        self.http = client

    def configured(self) -> bool:
        raise NotImplementedError

    async def complete(self, system: str, messages: list[ChatMessage], max_tokens: int = 1024) -> str:
        raise NotImplementedError


class ClaudeProvider(LLMProvider):
    name = "claude"

    def configured(self) -> bool:
        return bool(self.s.anthropic_api_key)

    async def complete(self, system, messages, max_tokens=1024):
        r = await self.http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.s.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.s.anthropic_model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            },
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


class OpenAIProvider(LLMProvider):
    name = "openai"

    def configured(self) -> bool:
        return bool(self.s.openai_api_key)

    async def complete(self, system, messages, max_tokens=1024):
        r = await self.http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.s.openai_api_key}"},
            json={
                "model": self.s.openai_model,
                "max_completion_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}]
                + [{"role": m.role, "content": m.content} for m in messages],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class GeminiProvider(LLMProvider):
    name = "gemini"

    def configured(self) -> bool:
        return bool(self.s.gemini_api_key)

    async def complete(self, system, messages, max_tokens=1024):
        r = await self.http.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.s.gemini_model}:generateContent",
            headers={"x-goog-api-key": self.s.gemini_api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [
                    {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                    for m in messages
                ],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        )
        r.raise_for_status()
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])


class OllamaProvider(LLMProvider):
    name = "ollama"

    def configured(self) -> bool:
        return bool(self.s.ollama_url)

    async def complete(self, system, messages, max_tokens=1024):
        r = await self.http.post(
            f"{self.s.ollama_url}/api/chat",
            json={
                "model": self.s.ollama_model,
                "stream": False,
                "keep_alive": "30m",
                "options": {"num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}]
                + [{"role": m.role, "content": m.content} for m in messages],
            },
            timeout=180.0,  # first load of a local model from disk is slow
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


class OllamaDockerProvider(OllamaProvider):
    """Same API, second endpoint: the Ollama container, used if the native one is down."""

    name = "ollama_docker"

    def __init__(self, s: Settings, client: httpx.AsyncClient):
        super().__init__(s.model_copy(update={"ollama_url": s.ollama_docker_url}), client)

    def configured(self) -> bool:
        return bool(self.s.ollama_url)


REGISTRY = {
    c.name: c for c in (ClaudeProvider, OpenAIProvider, GeminiProvider, OllamaProvider, OllamaDockerProvider)
}


def build_llm_chain(s: Settings, client: httpx.AsyncClient, on_failover=None) -> FallbackChain[LLMProvider]:
    providers = [REGISTRY[n](s, client) for n in s.llm_order if n in REGISTRY]
    return FallbackChain("llm", providers, timeout_s=190.0, on_failover=on_failover)
