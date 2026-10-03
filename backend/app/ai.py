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
    "vision": VisionAIProvider(),
    "embedding": EmbeddingProvider(),
}


def pick_chat_provider() -> AIProvider:
    # Cloud first (app must work when the PC is OFF). Local is optional acceleration.
    cloud = PROVIDERS["cloud"]
    if cloud.health()["available"]:
        return cloud
    local = PROVIDERS["local"]
    if local.health()["available"]:
        return local
    return cloud


def providers_health() -> list[dict]:
    return [p.health() for p in PROVIDERS.values()]
