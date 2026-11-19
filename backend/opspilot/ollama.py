import asyncio

import httpx

from .agent import AgentFailure
from .config import Settings


class Ollama:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def readiness(self) -> dict[str, str]:
        model = self.settings.ollama_model
        try:
            response = await self.request("/api/show", {"model": model}, timeout=3)
        except AgentFailure as exc:
            return {"status": "unavailable", "detail": str(exc)}
        capabilities = response.get("capabilities")
        if not isinstance(capabilities, list) or "tools" not in capabilities:
            return {"status": "unavailable", "detail": f"Model {model} lacks tool calling."}
        return {"status": "ready", "model": model}

    async def chat(
        self, messages: list[dict], tools: list[dict], *, output_schema: dict | None = None
    ) -> dict:
        request = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "tools": tools,
            "think": False,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 800},
        }
        if output_schema is not None:
            request["format"] = output_schema
        response = await self.request("/api/chat", request, timeout=self.settings.model_timeout_seconds)
        message = response.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise AgentFailure("Ollama returned an invalid chat response.")
        # Retain fields used by Ollama's native tool-calling conversation format.
        calls = message.get("tool_calls") or []
        return {"role": "assistant", "content": "" if calls else message.get("content", ""),
                "tool_calls": calls}

    async def request(self, path: str, payload: dict, timeout: float) -> dict:
        try:
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(
                    base_url=self.settings.ollama_url, timeout=timeout, trust_env=False
                ) as client:
                    response = await client.post(path, json=payload)
                    response.raise_for_status()
                data = response.json()
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AgentFailure("Ollama timed out while processing the request.") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                model = self.settings.ollama_model
                raise AgentFailure(f"Model {model} is missing. Run: ollama pull {model}") from exc
            raise AgentFailure(f"Ollama rejected the request (HTTP {exc.response.status_code}).") from exc
        except httpx.RequestError as exc:
            raise AgentFailure(
                f"Ollama is unreachable at {self.settings.ollama_url}. Start it with: ollama serve"
            ) from exc
        except ValueError as exc:
            raise AgentFailure("Ollama returned malformed JSON.") from exc
        if not isinstance(data, dict):
            raise AgentFailure("Ollama returned an unexpected response.")
        return data
