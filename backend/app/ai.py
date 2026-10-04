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
    """API Claude via le SDK officiel `anthropic`. Raisonnement profond à la demande, recherche Internet intégrée."""

    id = "claude"
    kind = "chat"
    # `_20260209` : recherche avec filtrage dynamique (Sonnet 5.5, Opus 5.5)
    WEB_TOOL = {"type": "web_search_20260209", "name": "web_search"}

    def health(self) -> dict:
        ok = bool(settings.anthropic_api_key)
        return {
            "id": self.id,
            "available": ok,
            "model": settings.anthropic_model if ok else None,
            "status": "ok" if ok else "not_configured",
            "detail": "" if ok else "ANTHROPIC_API_KEY absent. Raisonnement profond Claude NON DISPONIBLE.",
        }

    def _client(self):
        import anthropic

        opts = {"api_key": settings.anthropic_api_key, "timeout": 180.0, "max_retries": 2}
        if settings.anthropic_base_url:
            opts["base_url"] = settings.anthropic_base_url
        return anthropic.Anthropic(**opts)

    @staticmethod
    def _send(client, params: dict):
        """Essaie le repli serveur (refus de sécurité → modèle de secours) ; sans lui si l'API le rejette."""
        import anthropic

        try:
            return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        except anthropic.BadRequestError:
            return client.messages.create(**params)

    @staticmethod
    def _text_and_sources(resp) -> tuple[str, list[dict]]:
        parts, sources, seen = [], [], set()
        for block in resp.content or []:
            if getattr(block, "type", "") != "text":
                continue
            parts.append(block.text)
            for cit in getattr(block, "citations", None) or []:
                url = getattr(cit, "url", None)
                if url and url not in seen:
                    seen.add(url)
                    sources.append({"title": getattr(cit, "title", "") or url, "url": url})
        return "".join(parts).strip(), sources

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        model = kwargs.get("model") or settings.anthropic_model
        if not settings.anthropic_api_key:
            return AIResult("", self.id, model, False, "not_configured")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        params: dict = {"model": model, "max_tokens": kwargs.get("max_tokens", 8000), "messages": turns}
        if system:
            params["system"] = system
        if kwargs.get("effort"):
            params["output_config"] = {"effort": kwargs["effort"]}
        web = bool(kwargs.get("web")) and settings.web_search_enabled
        if web:
            params["tools"] = [{**self.WEB_TOOL, "max_uses": settings.web_search_max_uses}]
        try:
            client = self._client()
            try:
                resp = self._send(client, params)
                # recherche longue : l'API peut demander de reprendre le tour (pause_turn)
                for _ in range(3):
                    if getattr(resp, "stop_reason", "") != "pause_turn":
                        break
                    params["messages"] = turns + [{"role": "assistant", "content": resp.content}]
                    resp = self._send(client, params)
            except Exception:
                if not web:
                    raise
                # la recherche Internet est refusée (non activée sur le compte Anthropic ?) : on répond sans elle
                params.pop("tools", None)
                web = False
                resp = self._send(client, params)
            if getattr(resp, "stop_reason", "") == "refusal":
                return AIResult("", self.id, model, False, "refusal")
            text, sources = self._text_and_sources(resp)
            if web and sources:
                text += "\n\n**Sources**\n" + "\n".join(f"- [{s['title']}]({s['url']})" for s in sources[:6])
            return AIResult(text, self.id, model, bool(text), "" if text else "empty")
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
    """Ordre d'essai : modèle local d'abord ; Claude en premier si raisonnement profond demandé,
    sinon Claude (modèle rapide) seulement en dernier recours ; OpenAI-compatible entre les deux. Seuls les fournisseurs configurés sont gardés."""
    # Sans modèle local ni OpenAI, Claude devient le moteur courant (modèle rapide).
    order = ["claude", "local", "cloud"] if deep else ["local", "cloud", "claude"]
    return [PROVIDERS[k] for k in order if PROVIDERS[k].health()["available"]]


def pick_chat_provider(deep: bool = False) -> AIProvider:
    chain = provider_chain(deep)
    return chain[0] if chain else PROVIDERS["local"]


def chat_complete(messages: list[dict], deep: bool = False, web: bool = False, **kwargs) -> AIResult:
    """Essaie chaque fournisseur configuré jusqu'à obtenir un texte (PC éteint → secours)."""
    last = AIResult("", "none", "", False, "not_configured")
    for provider in provider_chain(deep):
        opts = dict(kwargs)
        if provider.id == "claude":
            opts.setdefault("model", settings.anthropic_model if deep else settings.anthropic_fast_model)
            opts.setdefault("effort", "high" if deep else "medium")
            opts["web"] = web
            opts.setdefault("max_tokens", 16000 if deep else 8000)
        res = provider.complete(messages, **opts)
        if res.available and res.text:
            return res
        last = res
    return last


def deep_available() -> bool:
    return PROVIDERS["claude"].health()["available"]


def providers_health() -> list[dict]:
    return [p.health() for p in PROVIDERS.values()]
