"""Couche d'abstraction AIProvider — cloud, local, vision, embeddings. Aucun fournisseur n'est verrouillé."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass
class AIResult:
    text: str
    provider: str
    model: str
    available: bool
    error: str = ""
    raw: dict | None = None


class AIProvider:
    id = "base"
    kind = "chat"

    def health(self) -> dict:
        raise NotImplementedError

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        raise NotImplementedError


class CloudAIProvider(AIProvider):
    id = "cloud"
    kind = "chat"

    def health(self) -> dict:
        ok = bool(settings.openai_api_key)
        return {
            "id": self.id,
            "available": ok,
            "model": settings.openai_model if ok else None,
            "status": "ok" if ok else "not_configured",
            "detail": "" if ok else "OPENAI_API_KEY absent. Le moteur métier UniC fonctionne sans LLM.",
        }

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        if not settings.openai_api_key:
            return AIResult("", self.id, settings.openai_model, False, "not_configured")
        url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": kwargs.get("model") or settings.openai_model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.2),
        }
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        try:
            with httpx.Client(timeout=60) as client:
                r = client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
            text = data["choices"][0]["message"].get("content") or ""
            return AIResult(text, self.id, payload["model"], True, raw=data)
        except Exception as exc:
            return AIResult("", self.id, settings.openai_model, False, str(exc))


class LocalAIProvider(AIProvider):
    id = "local"
    kind = "chat"

    def health(self) -> dict:
        ok = bool(settings.local_ai_url)
        return {
            "id": self.id,
            "available": ok,
            "model": settings.local_ai_model if ok else None,
            "status": "ok" if ok else "not_configured",
            "detail": "" if ok else "LOCAL_AI_URL absent. Le PC atelier n'est pas requis : le cloud UniC AI continue de fonctionner.",
        }

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        if not settings.local_ai_url:
            return AIResult("", self.id, settings.local_ai_model, False, "not_configured")
        url = settings.local_ai_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": kwargs.get("model") or settings.local_ai_model or "local",
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.2),
        }
        try:
            with httpx.Client(timeout=120) as client:
                r = client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
            text = data["choices"][0]["message"].get("content") or ""
            return AIResult(text, self.id, payload["model"], True, raw=data)
        except Exception as exc:
            return AIResult("", self.id, settings.local_ai_model, False, str(exc))


class ClaudeAIProvider(AIProvider):
    """API Claude (Anthropic Messages). Utilisée seulement pour le raisonnement profond demandé."""

    id = "claude"
    kind = "chat"

    def health(self) -> dict:
        ok = bool(settings.anthropic_api_key)
        return {
            "id": self.id,
            "available": ok,
            "model": settings.anthropic_model if ok else None,
            "status": "ok" if ok else "not_configured",
            "detail": "" if ok else "ANTHROPIC_API_KEY absent. Raisonnement profond Claude NON DISPONIBLE.",
        }

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        model = kwargs.get("model") or settings.anthropic_model
        if not settings.anthropic_api_key:
            return AIResult("", self.id, model, False, "not_configured")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        payload = {"model": model, "max_tokens": kwargs.get("max_tokens", 4096), "messages": turns}
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            with httpx.Client(timeout=180) as client:
                r = client.post(settings.anthropic_base_url.rstrip("/") + "/v1/messages", headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return AIResult(text, self.id, model, bool(text), raw=data)
        except Exception as exc:  # la clé n'apparaît jamais dans le message
            return AIResult("", self.id, model, False, f"claude: {type(exc).__name__}")


class VisionAIProvider(AIProvider):
    id = "vision"
    kind = "vision"

    def health(self) -> dict:
        ok = bool(settings.openai_api_key)
        return {
            "id": self.id,
            "available": ok,
            "status": "ok" if ok else "not_configured",
            "detail": "" if ok else "Vision NON DISPONIBLE sans clé cloud. Les photos sont stockées, pas interprétées.",
        }

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        return CloudAIProvider().complete(messages, **kwargs)


class EmbeddingProvider(AIProvider):
    id = "embedding"
    kind = "embedding"

    def health(self) -> dict:
        key = settings.embedding_api_key or settings.openai_api_key
        return {
            "id": self.id,
            "available": bool(key),
            "model": settings.embedding_model if key else None,
            "status": "ok" if key else "not_configured",
            "detail": "" if key else "Embeddings NON DISPONIBLES. La recherche documentaire utilise l'index lexical.",
        }

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        return AIResult("", self.id, settings.embedding_model, False, "use embed()")

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        key = settings.embedding_api_key or settings.openai_api_key
        if not key:
            return None
        base = (settings.embedding_base_url or settings.openai_base_url).rstrip("/")
        try:
            with httpx.Client(timeout=60) as client:
                r = client.post(
                    base + "/embeddings",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": settings.embedding_model, "input": texts},
                )
                r.raise_for_status()
                data = r.json()
            return [d["embedding"] for d in data["data"]]
        except Exception:
            return None


PROVIDERS: dict[str, AIProvider] = {
    "cloud": CloudAIProvider(),
    "local": LocalAIProvider(),
    "claude": ClaudeAIProvider(),
    "vision": VisionAIProvider(),
    "embedding": EmbeddingProvider(),
}


def provider_chain(deep: bool = False) -> list[AIProvider]:
    """Ordre d'essai : modèle local d'abord ; Claude seulement si raisonnement profond demandé ;
    OpenAI-compatible en secours. Seuls les fournisseurs configurés sont gardés."""
    order = ["claude", "local", "cloud"] if deep else ["local", "cloud"]
    return [PROVIDERS[k] for k in order if PROVIDERS[k].health()["available"]]


def pick_chat_provider(deep: bool = False) -> AIProvider:
    chain = provider_chain(deep)
    return chain[0] if chain else PROVIDERS["local"]


def chat_complete(messages: list[dict], deep: bool = False, **kwargs) -> AIResult:
    """Essaie chaque fournisseur configuré jusqu'à obtenir un texte (PC éteint → secours)."""
    last = AIResult("", "none", "", False, "not_configured")
    for provider in provider_chain(deep):
        res = provider.complete(messages, **kwargs)
        if res.available and res.text:
            return res
        last = res
    return last


def deep_available() -> bool:
    return PROVIDERS["claude"].health()["available"]


def providers_health() -> list[dict]:
    return [p.health() for p in PROVIDERS.values()]
