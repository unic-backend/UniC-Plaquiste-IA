"""Couche d'abstraction AIProvider — cloud, local, vision, embeddings. Aucun fournisseur n'est verrouillé."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

import json
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger("unic.ai")


@dataclass
class AIResult:
    text: str
    provider: str
    model: str
    available: bool
    error: str = ""
    raw: dict | None = None
    error_kind: str = ""   # classification de l'échec : quota | auth | request | network | server | refusal | other


def classify_exc(exc: Exception) -> str:
    """Classe un échec fournisseur : rate | quota | auth | request | network | server | other.

    « rate » (429, temporaire) et « quota » (402 / crédit épuisé) justifient TOUS DEUX la bascule vers
    Vibecode, mais seul « quota » (et « auth ») refroidit Claude : un 429 est transitoire, Claude est
    réessayé au message suivant. Une erreur de requête (400/404/422) ou un refus ne sera pas résolu
    par un autre fournisseur.
    """
    status = getattr(exc, "status_code", None)
    msg = str(getattr(exc, "message", "") or exc).lower()
    name = type(exc).__name__.lower()
    if status == 429 or "rate limit" in msg or "rate_limit" in msg or "too many requests" in msg:
        return "rate"
    if status == 402 or "credit" in msg or "balance" in msg or "quota" in msg:
        return "quota"
    if status in (401, 403) or "api key" in msg or "authentication" in msg or "unauthorized" in msg or "forbidden" in msg:
        return "auth"
    if status in (400, 404, 422) or "invalid" in msg or "bad request" in msg or "not found" in msg or "unknown model" in msg or "model" in msg and "not" in msg:
        return "request"
    if status and status >= 500:
        return "server"
    if "timeout" in name or "connection" in name or "connect" in name or "network" in name or "unreachable" in msg:
        return "network"
    return "other"


def explain_error(exc: Exception, who: str = "Claude", key_env: str = "ANTHROPIC_API_KEY",
                  console: str = "console.anthropic.com › Plans & Billing") -> str:
    """Raison lisible d'un échec fournisseur (jamais la clé, jamais le texte brut du serveur sans nettoyage)."""
    status = getattr(exc, "status_code", None)
    msg = str(getattr(exc, "message", "") or exc).lower()
    kind = classify_exc(exc)
    if kind == "quota" and status != 429:
        return f"crédit {who} épuisé : recharge sur {console}"
    if status == 401:
        return f"clé API refusée (vérifie {key_env} sur Render)"
    if status == 403:
        return f"accès refusé par {who} (permission du compte ou de la clé)"
    if status == 404:
        return "modèle introuvable ou non autorisé pour ta clé"
    if status == 429:
        return "trop de requêtes en même temps : réessaie dans une minute"
    if kind == "server":
        return f"{who} est surchargé ou en panne : réessaie dans un instant"
    if status == 400:
        return f"requête refusée par {who} ({msg[:120]})"
    name = type(exc).__name__
    if kind == "network":
        return f"connexion à {who} impossible ou trop lente : réessaie"
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
        sys_msgs = [m for m in messages if m["role"] == "system"]
        turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        params: dict = {"model": model, "max_tokens": kwargs.get("max_tokens", 8000), "messages": turns}
        if any(m.get("cache") for m in sys_msgs):
            # Cache de prompt (réduit le prix des textes qui se répètent à chaque message ; le contenu lu par l'IA ne change pas) :
            # la partie stable (règles) est marquée ; la partie qui varie (mémoire, base, fichiers) vient après, sans marque.
            params["system"] = [{"type": "text", "text": m["content"], **({"cache_control": {"type": "ephemeral"}} if m.get("cache") else {})}
                                for m in sys_msgs if m["content"]]
        elif sys_msgs:
            params["system"] = "\n\n".join(m["content"] for m in sys_msgs)
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
                return AIResult("", self.id, model, False, "refusal", raw={"tools_used": used, "usage": tally}, error_kind="refusal")
            text, sources = self._text_and_sources(resp)
            if web and sources:
                text += "\n\n**Sources**\n" + "\n".join(f"- [{s['title']}]({s['url']})" for s in sources[:6])
            return AIResult(text, self.id, model, bool(text), "" if text else "empty", raw={"tools_used": used, "usage": tally})
        except Exception as exc:  # la clé n'apparaît jamais dans le message
            return AIResult("", self.id, model, False, f"claude: {explain_error(exc)}",
                            raw={"tools_used": used, "usage": tally}, error_kind=classify_exc(exc))
        finally:
            _usage.TALLY.reset(_tok)


class VibecodeAIProvider(AIProvider):
    """Vibecode.moe — relais compatible Anthropic Messages (doc : vibecode.moe/setup/cc), fournisseur SECONDAIRE.

    Même protocole (SDK officiel `anthropic`, base_url=https://vibecode.moe), donc mêmes familles de modèles,
    streaming et outils client. Différences VOLONTAIRES avec ClaudeAIProvider, parce que c'est un endpoint tiers :
    - pas de bêta Anthropic (`server-side-fallback`) : non garanti hors api.anthropic.com ;
    - pas d'outil serveur `web_search_20260209` : spécifique à Anthropic (la recherche Internet reste Claude) ;
    - « system » envoyé en texte simple : pas de cache_control de prompt sur le relais ;
    - si une option avancée (effort / thinking / tools) est refusée (400), UN seul réessai en requête minimale
      (texte seul) : dégradation interne, jamais une boucle, jamais un autre fournisseur.
    """

    id = "vibecode"
    kind = "chat"
    MAX_ROUNDS = 8  # tours d'outils maximum par réponse

    def health(self) -> dict:
        ok = bool(settings.vibecode_enabled and settings.vibecode_api_key)
        return {
            "id": self.id,
            "available": ok,
            "model": settings.vibecode_sonnet_model if ok else None,
            "status": "ok" if ok else "not_configured",
            "detail": "" if ok else "VIBECODE_API_KEY absent (ou VIBECODE_ENABLED=false). Relais secondaire inactif : Anthropic reste prioritaire.",
        }

    def _client(self):
        import anthropic

        # base_url SANS « /v1 » : le SDK ajoute lui-même /v1/messages (doc Vibecode : ANTHROPIC_BASE_URL=https://vibecode.moe)
        return anthropic.Anthropic(
            api_key=settings.vibecode_api_key,
            base_url=settings.vibecode_base_url or "https://vibecode.moe",
            timeout=settings.vibecode_timeout_s,
            max_retries=settings.vibecode_max_retries,   # retries internes (429/5xx/connexion) avec backoff exponentiel
        )

    @staticmethod
    def _send_stream(client, params: dict, cb):
        """Flux standard (pas de bêta) : le texte arrive mot à mot."""

        def attempt(manager):
            with manager as stream:
                for ev in stream:
                    kind = getattr(ev, "type", "")
                    if kind == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                        cb({"t": "delta", "text": ev.delta.text})
                return stream.get_final_message()

        cb({"t": "reset"})
        return attempt(client.messages.stream(**params))

    @staticmethod
    def _send(client, params: dict):
        from app import usage

        cb = STREAM_CB.get()
        resp = None
        if cb is not None:
            try:
                resp = VibecodeAIProvider._send_stream(client, params, cb)
            except Exception:  # flux impossible : on retombe sur l'appel classique (le texte déjà affiché est effacé)
                cb({"t": "reset"})
        if resp is None:
            resp = client.messages.create(**params)
        usage.tally(resp)
        return resp

    def _run(self, client, params: dict, handler, used: list[str]):
        """Boucle tool_use (connecteurs) / pause_turn. Rend la dernière réponse."""
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
        # L'identifiant Vibecode est toujours celui réellement envoyé (Sonnet/Opus/Haiku configurables dans .env).
        model = vibecode_model_for(kwargs.get("model"))
        if not (settings.vibecode_enabled and settings.vibecode_api_key):
            return AIResult("", self.id, model, False, "not_configured", error_kind="other")
        sys_msgs = [m for m in messages if m["role"] == "system" and isinstance(m.get("content"), str)]
        turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
        params: dict = {"model": model, "max_tokens": kwargs.get("max_tokens", 8000), "messages": turns}
        if sys_msgs:
            params["system"] = "\n\n".join(m["content"] for m in sys_msgs)   # texte simple, sans cache_control
        if kwargs.get("effort"):
            params["output_config"] = {"effort": kwargs["effort"]}
        if kwargs.get("thinking"):
            params["thinking"] = {"type": "adaptive"}
        tools = list(kwargs.get("tools") or [])
        handler = kwargs.get("tool_handler")
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
            except Exception as exc:
                import anthropic
                rich = any(k in params for k in ("output_config", "thinking", "tools"))
                if not (rich and isinstance(exc, anthropic.BadRequestError)):
                    raise
                # Le relais rejette une option avancée : UN seul réessai en requête minimale (texte seul).
                logger.debug("vibecode : option avancée refusée (%s), réessai en requête minimale", type(exc).__name__)
                minimal = {k: params[k] for k in ("model", "max_tokens", "messages", "system") if k in params}
                used.clear()
                resp = self._run(client, minimal, None, used)
            if getattr(resp, "stop_reason", "") == "refusal":
                return AIResult("", self.id, model, False, "refusal", raw={"tools_used": used, "usage": tally}, error_kind="refusal")
            text, _sources = ClaudeAIProvider._text_and_sources(resp)   # pas de sources web côté Vibecode
            return AIResult(text, self.id, model, bool(text), "" if text else "empty", raw={"tools_used": used, "usage": tally})
        except Exception as exc:  # la clé n'apparaît jamais dans le message
            return AIResult("", self.id, model, False,
                            f"vibecode: {explain_error(exc, who='Vibecode', key_env='VIBECODE_API_KEY', console='vibecode.moe (crédits)')}",
                            raw={"tools_used": used, "usage": tally}, error_kind=classify_exc(exc))
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


def vibecode_model_for(requested: str | None) -> str:
    """Traduit l'identifiant demandé (familles Anthropic officielles) vers l'identifiant Vibecode équivalent.

    Sonnet = tâches quotidiennes (programmation, rédaction) · Opus = raisonnement et problèmes complexes ·
    Haiku = voix rapide. Les identifiants Vibecode sont configurables (.env) ; le résultat est celui
    réellement envoyé à l'API et enregistré dans AIResult.model.
    """
    req = (requested or "").lower()
    if "opus" in req:
        return settings.vibecode_opus_model
    if "haiku" in req:
        return settings.vibecode_haiku_model or settings.vibecode_sonnet_model
    return settings.vibecode_sonnet_model


def _readonly_tool_guard(handler, safe_names):
    """Enveloppe un handler d'outils pour le relais Vibecode : tout outil hors lecture seule
    (agents.SAFE_TOOLS) est refusé SANS exécution — même un nom inventé par le modèle."""
    def guarded(name, args):
        if name not in safe_names:
            return {"error": "outil non autorisé"}
        return handler(name, args)
    return guarded


# ---------- refroidisseur (circuit breaker) : après un échec « quota »/« auth », ne pas réessayer tout de suite ----------
_CB_LOCK = threading.Lock()
_CB: dict[str, tuple[float, str]] = {}   # id fournisseur -> (monotonic du dernier échec, kind)


def _cooldown_active(pid: str, kinds: tuple[str, ...] = ("quota", "auth")) -> bool:
    """Vrai si le fournisseur a échoué récemment (quota/auth) : les appels suivants sautent directement au relais."""
    window = settings.ai_quota_cooldown_s
    if window <= 0:
        return False
    with _CB_LOCK:
        hit = _CB.get(pid)
    return bool(hit and hit[1] in kinds and (time.monotonic() - hit[0]) < window)


def _mark_failure(pid: str, kind: str) -> None:
    with _CB_LOCK:
        _CB[pid] = (time.monotonic(), kind)


def reset_circuit_breakers() -> None:
    """Oublie les refroidissements (tests, rechargement de configuration)."""
    with _CB_LOCK:
        _CB.clear()


PROVIDERS: dict[str, AIProvider] = {
    "cloud": CloudAIProvider(),
    "local": LocalAIProvider(),
    "claude": ClaudeAIProvider(),
    "vibecode": VibecodeAIProvider(),
    "pc": PCWorkerProvider(),
    "vision": VisionAIProvider(),
    "embedding": EmbeddingProvider(),
}


def provider_chain(deep: bool = False) -> list[AIProvider]:
    """Ordre d'essai : Claude (Anthropic officiel) TOUJOURS en premier ; Vibecode (relais payant secondaire)
    juste après ; puis les secours locaux (PC, modèle local, OpenAI-compatible). Seuls les fournisseurs configurés sont gardés."""
    if not settings.llm_enabled:
        return []
    order = ["claude", "vibecode", "pc", "local", "cloud"]
    return [PROVIDERS[k] for k in order if PROVIDERS[k].health()["available"]]


def pick_chat_provider(deep: bool = False) -> AIProvider:
    chain = provider_chain(deep)
    return chain[0] if chain else PROVIDERS["local"]


def chat_complete(messages: list[dict], deep: bool = False, web: bool = False, tools: list | None = None,
                  tool_handler=None, **kwargs) -> AIResult:
    """Essaie chaque fournisseur configuré jusqu'à obtenir un texte (PC éteint → secours).

    Basculement vers Vibecode (relais payant secondaire) MAÎTRISÉ, jamais aveugle :
    - Anthropic officiel d'abord. Seuls ses échecs classés « quota » (crédit), « rate » (429), « auth »,
      « network » ou « server » autorisent l'essai de Vibecode ; une erreur de requête (400/404/422),
      un refus ou une erreur inconnue ne déclenchent PAS de bascule vers un fournisseur payant.
    - Un seul passage, ordre fixe, séquentiel : jamais deux requêtes payantes simultanées pour une même
      tâche, et jamais de retour arrière (Vibecode en échec → secours local, pas un nouvel essai Claude).
    - Tentatives limitées : le SDK gère les retries internes (429/5xx/connexion, backoff exponentiel,
      max_retries borné) ; aucun retry applicatif au-delà, aucune boucle de basculement.
    - Refroidissement : après un échec « quota » (402/crédit épuisé) ou « auth » (clé refusée) d'Anthropic,
      celui-ci n'est pas réessayé pendant AI_QUOTA_COOLDOWN_S secondes. Un 429 (« rate ») est transitoire :
      il ne refroidit PAS (Claude est réessayé au message suivant). Et le refroidissement ne s'applique que
      si Vibecode est configuré : sans relais, Claude est toujours essayé.
    - Vibecode n'a que les outils en LECTURE seule (agents.SAFE_TOOLS) : le relais ne crée, ne modifie
      ni ne supprime aucun document. Le handler est enveloppé : tout appel d'outil hors SAFE_TOOLS
      (même un nom inventé par le modèle) est refusé SANS exécution.
    """
    last = AIResult("", "none", "", False, "not_configured")
    skip_vibecode = False
    has_vibecode = PROVIDERS["vibecode"].health()["available"]   # sans relais configuré, Claude est toujours essayé
    for provider in provider_chain(deep):
        if provider.id == "vibecode" and skip_vibecode:
            continue   # l'échec précédent ne justifiait pas un appel payant (requête refusée, refus, erreur inconnue)
        if provider.id == "claude" and has_vibecode and _cooldown_active("claude"):
            last = AIResult("", "claude", settings.anthropic_model, False, "cooldown_quota", error_kind="quota")
            continue   # crédit/auth récent + relais configuré : on ne martèle pas l'officiel, le relais prend le relais
        if provider.id not in ("claude", "vibecode"):   # les autres moteurs ne connaissent ni le cache ni plusieurs messages « system » : un seul, sans marque
            sysm = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            rest = [{k: v for k, v in m.items() if k != "cache"} for m in messages if m["role"] != "system"]
            plain = ([{"role": "system", "content": sysm}] if sysm else []) + rest
        else:
            plain = messages
        opts = dict(kwargs)
        if provider.id == "claude":
            opts.setdefault("model", settings.anthropic_model if deep else settings.anthropic_fast_model)
            opts.setdefault("effort", "high" if deep else "medium")
            opts["web"] = web
            opts["tools"], opts["tool_handler"] = tools, tool_handler
            opts.setdefault("max_tokens", 16000 if deep else 8000)
        elif provider.id == "vibecode":
            # traduction de l'identifiant demandé vers l'identifiant Vibecode (Sonnet/Opus/Haiku configurables)
            wanted = opts.pop("model", None) or (settings.anthropic_model if deep else settings.anthropic_fast_model)
            opts["model"] = vibecode_model_for(wanted)
            # Le relais n'expose que les outils en LECTURE seule (agents.SAFE_TOOLS) : jamais de création de
            # documents. Le handler est enveloppé : un outil non sûr (même un nom inventé par le modèle)
            # est refusé SANS exécution.
            if tools:
                from app import agents
                safe = [t for t in tools if isinstance(t, dict) and t.get("name") in agents.SAFE_TOOLS]
                opts["tools"] = safe or None
                opts["tool_handler"] = (_readonly_tool_guard(tool_handler, agents.SAFE_TOOLS)
                                        if safe and tool_handler is not None else None)
            else:
                opts["tools"], opts["tool_handler"] = None, None
            opts.setdefault("max_tokens", 16000 if deep else 8000)
            # « web » ignoré volontairement : l'outil serveur web_search est spécifique à Anthropic, pas au relais
        res = provider.complete(plain, **opts)
        if res.available and res.text:
            return res
        if provider.id == "claude":
            if res.error_kind in ("quota", "auth"):
                # Refroidissement UNIQUEMENT sur crédit épuisé (402) ou clé refusée : un 429 (« rate ») est
                # transitoire, il bascule vers Vibecode mais ne refroidit pas Claude.
                _mark_failure("claude", res.error_kind)
            if res.error_kind not in ("quota", "rate", "auth", "network", "server"):
                skip_vibecode = True   # requête refusée / refus / erreur inconnue : pas de bascule aveugle vers un payant
        last = res
    return last


def deep_available() -> bool:
    return PROVIDERS["claude"].health()["available"]


def providers_health() -> list[dict]:
    return [p.health() for p in PROVIDERS.values()]
