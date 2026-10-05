"""Couche d'abstraction AIProvider — cloud, local, vision, embeddings. Aucun fournisseur n'est verrouillé."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

import json
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


def explain_error(exc: Exception) -> str:
    """Raison lisible d'un échec Claude (jamais la clé, jamais le texte brut du serveur sans nettoyage)."""
    status = getattr(exc, "status_code", None)
    msg = str(getattr(exc, "message", "") or exc).lower()
    if "credit" in msg or "balance" in msg or status == 402:
        return "crédit Anthropic épuisé : recharge sur console.anthropic.com › Plans & Billing"
    if status == 401:
        return "clé API refusée (vérifie ANTHROPIC_API_KEY sur Render)"
    if status == 403:
        return "accès refusé par Anthropic (permission du compte ou de la clé)"
    if status == 404:
        return "modèle introuvable ou non autorisé pour ta clé"
    if status == 429:
        return "trop de requêtes en même temps : réessaie dans une minute"
    if status and status >= 500:
        return "Claude est surchargé ou en panne : réessaie dans un instant"
    if status == 400:
        return f"requête refusée par Claude ({msg[:120]})"
    name = type(exc).__name__
    if "timeout" in name.lower() or "connection" in name.lower():
        return "connexion à Claude impossible ou trop lente : réessaie"
    return name


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


# Rappel de progression pour l'écran (flux en direct) : {"t": "status"|"delta"|"reset", ...}. Absent = réponse d'un bloc.
STREAM_CB: ContextVar = ContextVar("unic_stream_cb", default=None)

STREAM_SINK: ContextVar = ContextVar("unic_stream_sink", default=None)  # où vont les événements (posé par l'API)


@contextmanager
def live():
    """Active le flux en direct pour UN appel (la réponse principale), pas pour les appels annexes (mémoire…)."""
    tok = STREAM_CB.set(STREAM_SINK.get())
    try:
        yield
    finally:
        STREAM_CB.reset(tok)


TOOL_LABELS = {
    "get_prices": "Je regarde les prix…", "calculate_materials": "Je calcule les quantités…",
    "create_quote": "Je prépare le devis…", "create_invoice": "Je prépare la facture…",
    "create_purchase_order": "Je prépare le bon de commande…", "create_delivery_note": "Je prépare le bon de livraison…",
    "revise_document": "Je corrige le document…", "list_documents": "Je cherche dans tes documents…",
    "list_directory": "Je consulte l'annuaire…", "read_inbox": "Je lis ta boîte mail…", "read_email": "Je lis le mail…",
    "list_google_reviews": "Je regarde les avis Google…", "google_profile_audit": "J'analyse ta fiche Google…",
    "self_check": "Je me vérifie…", "list_incidents": "Je regarde mes problèmes…", "improve_myself": "Je lance ma correction…",
    "create_agent": "Je crée l'agent…",
}


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

        from app import usage

        cb = STREAM_CB.get()
        resp = None
        if cb is not None:
            try:
                resp = ClaudeAIProvider._send_stream(client, params, cb)
            except Exception:  # flux impossible : on retombe sur l'appel classique (le texte déjà affiché est effacé)
                cb({"t": "reset"})
        if resp is None:
            try:
                resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
            except anthropic.BadRequestError:
                resp = client.messages.create(**params)
        usage.tally(resp)
        return resp

    @staticmethod
    def _send_stream(client, params: dict, cb):
        """Même requête en flux : le texte arrive mot à mot, les recherches Internet sont annoncées."""
        import anthropic

        def attempt(manager):
            with manager as stream:
                for ev in stream:
                    kind = getattr(ev, "type", "")
                    if kind == "content_block_start" and getattr(ev.content_block, "type", "") == "server_tool_use":
                        cb({"t": "status", "text": "Je cherche sur Internet…"})
                    elif kind == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                        cb({"t": "delta", "text": ev.delta.text})
                return stream.get_final_message()

        cb({"t": "reset"})
        try:
            return attempt(client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params))
        except anthropic.BadRequestError:
            cb({"t": "reset"})
            return attempt(client.messages.stream(**params))

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

    MAX_ROUNDS = 8  # tours d'outils maximum par réponse

    def _run(self, client, params: dict, handler, used: list[str]):
        """Boucle : pause_turn (recherche longue) et tool_use (connecteurs). Rend la dernière réponse."""
        resp = self._send(client, params)
        for _ in range(self.MAX_ROUNDS):
            stop = getattr(resp, "stop_reason", "")
            if stop == "pause_turn":
                params["messages"] = params["messages"] + [{"role": "assistant", "content": resp.content}]
            elif stop == "tool_use" and handler is not None:
                results = []
                for block in resp.content:
                    if getattr(block, "type", "") != "tool_use":
                        continue
                    used.append(block.name)
                    cb = STREAM_CB.get()
                    if cb is not None:
                        cb({"t": "status", "text": TOOL_LABELS.get(block.name, "Je travaille…")})
                    out = handler(block.name, dict(block.input or {}))
                    item = {"type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(out, ensure_ascii=False, default=str)[:20000]}
                    if isinstance(out, dict) and out.get("error"):
                        item["is_error"] = True
                    results.append(item)
                params["messages"] = params["messages"] + [
                    {"role": "assistant", "content": resp.content},
                    {"role": "user", "content": results},  # tous les résultats dans UN seul message
                ]
            else:
                break
            resp = self._send(client, params)
        return resp

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
        if kwargs.get("thinking"):
            params["thinking"] = {"type": "adaptive"}   # raisonnement profond (ex. atelier de réparation)
        web = bool(kwargs.get("web")) and settings.web_search_enabled
        client_tools = list(kwargs.get("tools") or [])
        handler = kwargs.get("tool_handler")
        tools = ([{**self.WEB_TOOL, "max_uses": settings.web_search_max_uses}] if web else []) + client_tools
        if tools:
            params["tools"] = tools
        used: list[str] = []
        from app import usage as _usage
        tally: list[dict] = []
        _tok = _usage.TALLY.set(tally)
        try:
            client = self._client()
            try:
                resp = self._run(client, params, handler, used)
            except Exception:
                if not web:
                    raise
                # la recherche Internet est refusée (non activée sur le compte Anthropic ?) : on répond sans elle
                params["messages"], web, used = turns, False, []
                if client_tools:
                    params["tools"] = client_tools
                else:
                    params.pop("tools", None)
                resp = self._run(client, params, handler, used)
            if getattr(resp, "stop_reason", "") == "refusal":
                return AIResult("", self.id, model, False, "refusal", raw={"tools_used": used, "usage": tally})
            text, sources = self._text_and_sources(resp)
            if web and sources:
                text += "\n\n**Sources**\n" + "\n".join(f"- [{s['title']}]({s['url']})" for s in sources[:6])
            return AIResult(text, self.id, model, bool(text), "" if text else "empty", raw={"tools_used": used, "usage": tally})
        except Exception as exc:  # la clé n'apparaît jamais dans le message
            return AIResult("", self.id, model, False, f"claude: {explain_error(exc)}", raw={"tools_used": used, "usage": tally})
        finally:
            _usage.TALLY.reset(_tok)


class PCWorkerProvider(AIProvider):
    """Secours quand Claude ne répond pas : d'abord les réponses validées (Retenir), puis le modèle local du PC s'il est allumé."""
    id = "pc"
    kind = "chat"

    def health(self) -> dict:
        from app import localworker
        st = localworker.status()
        return {"id": self.id, "available": st["online"], "model": st["model"] or None,
                "status": "ok" if st["online"] else "offline",
                "detail": "" if st["online"] else "PC éteint ou appli Windows fermée : seules les réponses validées servent de secours."}

    def complete(self, messages: list[dict], **kwargs) -> AIResult:
        from app import learned, localworker
        from app.database import SessionLocal
        question = next((m["content"] for m in reversed(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        with SessionLocal() as db:
            known = learned.local_reply(db, question)
            if known:   # lecture seule : pas d'écriture pendant que la conversation s'enregistre
                return AIResult(known, "learned", "réponses validées", True)
        text, model = localworker.ask(None, messages)
        if text:
            return AIResult(text, self.id, model or "local", True)
        return AIResult("", self.id, "", False, "offline")


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
    "pc": PCWorkerProvider(),
    "vision": VisionAIProvider(),
    "embedding": EmbeddingProvider(),
}


def provider_chain(deep: bool = False) -> list[AIProvider]:
    """Ordre d'essai : modèle local d'abord ; Claude en premier si raisonnement profond demandé,
    sinon Claude (modèle rapide) seulement en dernier recours ; OpenAI-compatible entre les deux. Seuls les fournisseurs configurés sont gardés."""
    # Sans modèle local ni OpenAI, Claude devient le moteur courant (modèle rapide).
    order = ["claude", "pc", "local", "cloud"]   # Claude répond TOUJOURS en premier ; les autres ne sont qu'un secours
    return [PROVIDERS[k] for k in order if PROVIDERS[k].health()["available"]]


def pick_chat_provider(deep: bool = False) -> AIProvider:
    chain = provider_chain(deep)
    return chain[0] if chain else PROVIDERS["local"]


def chat_complete(messages: list[dict], deep: bool = False, web: bool = False, tools: list | None = None,
                  tool_handler=None, **kwargs) -> AIResult:
    """Essaie chaque fournisseur configuré jusqu'à obtenir un texte (PC éteint → secours)."""
    last = AIResult("", "none", "", False, "not_configured")
    for provider in provider_chain(deep):
        opts = dict(kwargs)
        if provider.id == "claude":
            opts.setdefault("model", settings.anthropic_model if deep else settings.anthropic_fast_model)
            opts.setdefault("effort", "high" if deep else "medium")
            opts["web"] = web
            opts["tools"], opts["tool_handler"] = tools, tool_handler
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
