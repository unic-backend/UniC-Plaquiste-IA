"""Tests du fournisseur secondaire Vibecode (relais Anthropic-compatible) et du basculement Claude → Vibecode → local.

100 % simulé (SDK `anthropic` et HTTP mockés) : AUCUN appel payant n'est fait.

Couvre :
- Vibecode seul (clé/base_url propres, protocole Messages, pas de bêta Anthropic, pas de web_search serveur) ;
- Anthropic seul (non-régression) et priorité d'Anthropic quand les deux sont configurés ;
- basculement après quota épuisé (429/402), clé refusée (401) et erreur réseau simulées ;
- PAS de bascule sur erreur de requête (400) ni sur refus ;
- les deux API en panne → fournisseur local ;
- sélection Sonnet (quotidien) / Opus (profond) / Haiku (voix) avec enregistrement du modèle réel ;
- outils (boucle tool_use) et streaming côté Vibecode ;
- refroidissement d'Anthropic après un quota (pas de nouvel essai payant chez Anthropic) ;
- conservation de la mémoire (savoir validé) quand les deux API externes sont indisponibles ;
- aucune fuite de clé dans les erreurs ; tarifs Vibecode dans le compteur d'usage.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace as _NS

import pytest

os.environ.setdefault("UNIC_DATA_DIR", str(Path("/tmp/unic-test-data-vibecode")))
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
os.environ.setdefault("UNIC_SECRET_KEY", "test-secret-key-not-for-prod")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import ai  # noqa: E402
from app.config import settings  # noqa: E402


# ---------- faux SDK anthropic ----------

def _usage():
    return _NS(input_tokens=1_000_000, output_tokens=500_000, cache_read_input_tokens=10,
               cache_creation_input_tokens=5, server_tool_use=None)


def _resp(text, stop="end_turn", content=None):
    block = _NS(type="text", text=text, citations=None)
    return _NS(content=content or [block], stop_reason=stop, model="m", usage=_usage())


def _err(cls, status, message):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=req), body=None)


class _FakeStream:
    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for block in self._final.content:
            if getattr(block, "type", "") == "text":
                yield _NS(type="content_block_delta", delta=_NS(type="text_delta", text=block.text))

    def get_final_message(self):
        return self._final


class FakeAnthropic:
    """Faux client du SDK officiel : capture les appels, rejoue un script (réponse ou exception)."""

    def __init__(self, reply):
        self.calls = []
        self.reply = reply
        self.messages = _NS(create=self._create, stream=self._stream)
        self.beta = _NS(messages=_NS(create=self._beta))

    def _create(self, **kw):
        self.calls.append(("create", kw))
        out = self.reply("create", kw)
        if isinstance(out, Exception):
            raise out
        return out

    def _beta(self, **kw):
        self.calls.append(("beta", kw))
        out = self.reply("beta", kw)
        if isinstance(out, Exception):
            raise out
        return out

    def _stream(self, **kw):
        self.calls.append(("stream", kw))
        out = self.reply("stream", kw)
        if isinstance(out, Exception):
            raise out
        return _FakeStream(out)


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def clean_ai(monkeypatch):
    """Isole chaque test : aucune clé par défaut, refroidissements remis à zéro."""
    for attr, val in (("anthropic_api_key", ""), ("vibecode_api_key", ""), ("vibecode_enabled", True),
                      ("local_ai_url", ""), ("openai_api_key", ""), ("llm_enabled", True),
                      ("ai_quota_cooldown_s", 300)):
        monkeypatch.setattr(settings, attr, val)
    ai.reset_circuit_breakers()
    yield
    ai.reset_circuit_breakers()


def _install(monkeypatch, cls, reply):
    fake = FakeAnthropic(reply)
    monkeypatch.setattr(cls, "_client", lambda self: fake)
    return fake


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


MSGS = [{"role": "system", "content": "règles"}, {"role": "user", "content": "q"}]


# ---------- chaîne, santé, configuration ----------

def test_vibecode_chain_and_health(monkeypatch):
    assert [p.id for p in ai.provider_chain()] == []
    monkeypatch.setattr(settings, "vibecode_api_key", "vk-test")
    assert [p.id for p in ai.provider_chain()] == ["vibecode"]
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "local_ai_url", "http://local/v1")
    assert [p.id for p in ai.provider_chain()] == ["claude", "vibecode", "local"]
    health = {p["id"]: p for p in ai.providers_health()}
    assert health["vibecode"]["available"] and health["vibecode"]["model"] == settings.vibecode_sonnet_model
    # coupe-circuit : Vibecode désactivé = absent de la chaîne, Anthropic inchangé
    monkeypatch.setattr(settings, "vibecode_enabled", False)
    assert [p.id for p in ai.provider_chain()] == ["claude", "local"]
    # LLM_ENABLED=false coupe tout (comportement existant, non régressé)
    monkeypatch.setattr(settings, "vibecode_enabled", True)
    monkeypatch.setattr(settings, "llm_enabled", False)
    assert ai.provider_chain() == []


def test_vibecode_alone_uses_its_own_key_and_base_url(monkeypatch):
    monkeypatch.setattr(settings, "vibecode_api_key", "vk-test-secret")
    captured = {}

    def spy(**kw):
        captured.update(kw)
        return FakeAnthropic(lambda kind, kw2: _resp("réponse vibecode"))

    monkeypatch.setattr("anthropic.Anthropic", spy)
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.available and res.text == "réponse vibecode"
    assert res.provider == "vibecode" and res.model == settings.vibecode_sonnet_model
    # le relais a SA clé et SON endpoint (doc vibecode.moe/setup/cc : ANTHROPIC_BASE_URL=https://vibecode.moe)
    assert captured["api_key"] == "vk-test-secret"
    assert captured["base_url"] == "https://vibecode.moe"
    assert captured["max_retries"] == settings.vibecode_max_retries


def test_vibecode_request_has_no_anthropic_betas_and_no_web_search_tool(monkeypatch):
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ok"))
    ai.chat_complete(MSGS, web=True)   # web=True ne doit PAS activer l'outil serveur web_search d'Anthropic
    kind, kw = vibecode.calls[-1]
    assert kind == "create"
    assert "betas" not in kw and "fallbacks" not in kw          # bêta server-side-fallback : spécifique Anthropic
    assert "tools" not in kw                                   # web_search_20260209 : spécifique Anthropic
    assert kw["system"] == "règles" and kw["messages"] == [{"role": "user", "content": "q"}]
    assert isinstance(kw["system"], str)                       # texte simple, pas de cache_control de prompt


# ---------- priorité Anthropic ----------

def test_anthropic_stays_first_when_both_configured(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    claude = _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: _resp("réponse claude"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("réponse vibecode"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.provider == "claude" and res.text == "réponse claude"
    assert len(claude.calls) == 1 and len(vibecode.calls) == 0   # Vibecode jamais appelé tant qu'Anthropic répond


def test_anthropic_alone_still_works(monkeypatch):
    """Non-régression : Anthropic seul, sans Vibecode configuré."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    claude = _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: _resp("réponse claude"))
    res = ai.chat_complete(MSGS, deep=True)
    assert res.available and res.provider == "claude" and res.text == "réponse claude"
    assert res.model == settings.anthropic_model
    assert claude.calls[-1][1]["model"] == settings.anthropic_model


# ---------- basculement (failover) ----------

def test_failover_to_vibecode_when_anthropic_quota_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    claude = _install(monkeypatch, ai.ClaudeAIProvider,
                      lambda kind, kw: _err(anthropic.RateLimitError, 429, "rate limit"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("réponse vibecode"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.available and res.provider == "vibecode" and res.text == "réponse vibecode"
    assert res.model == settings.vibecode_sonnet_model          # le modèle RÉEL est enregistré
    assert len(vibecode.calls) == 1                             # UNE seule requête payante chez Vibecode


def test_failover_to_vibecode_when_anthropic_payment_required(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    _install(monkeypatch, ai.ClaudeAIProvider,
             lambda kind, kw: _err(anthropic.APIStatusError, 402, "credit balance too low"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("réponse vibecode"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.available and res.provider == "vibecode"
    assert len(vibecode.calls) == 1


def test_failover_to_vibecode_when_anthropic_key_refused(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    _install(monkeypatch, ai.ClaudeAIProvider,
             lambda kind, kw: _err(anthropic.AuthenticationError, 401, "invalid x-api-key"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("réponse vibecode"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.available and res.provider == "vibecode"
    assert len(vibecode.calls) == 1


def test_failover_to_vibecode_on_network_error(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    _install(monkeypatch, ai.ClaudeAIProvider,
             lambda kind, kw: anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("réponse vibecode"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.available and res.provider == "vibecode"
    assert len(vibecode.calls) == 1


# ---------- PAS de bascule aveugle ----------

def test_no_failover_on_request_error(monkeypatch):
    """Une requête refusée (400) n'est pas résolue par un autre fournisseur payant : Vibecode n'est PAS appelé."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    _install(monkeypatch, ai.ClaudeAIProvider,
             lambda kind, kw: _err(anthropic.BadRequestError, 400, "invalid request"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ne doit pas être appelé"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert not res.available
    assert len(vibecode.calls) == 0


def test_no_failover_on_refusal(monkeypatch):
    """Un refus de sécurité n'est pas une indisponibilité : pas de bascule vers un payant."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: _resp("", stop="refusal"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ne doit pas être appelé"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.error == "refusal"
    assert len(vibecode.calls) == 0


def test_no_failover_on_unknown_error(monkeypatch):
    """Une erreur non classée ne déclenche pas non plus un appel payant (sécurité anti-coût)."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: RuntimeError("quelque chose d'inattendu"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ne doit pas être appelé"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert not res.available
    assert len(vibecode.calls) == 0


# ---------- les deux API en panne → secours local ----------

def test_local_answers_when_both_cloud_apis_fail(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    monkeypatch.setattr(settings, "local_ai_url", "http://local/v1")
    _install(monkeypatch, ai.ClaudeAIProvider,
             lambda kind, kw: _err(anthropic.RateLimitError, 429, "quota"))
    _install(monkeypatch, ai.VibecodeAIProvider,
             lambda kind, kw: _err(anthropic.InternalServerError, 500, "down"))
    real = httpx.Client
    monkeypatch.setattr(ai.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "secours local"}}]})), **kw))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert res.available and res.provider == "local" and res.text == "secours local"


# ---------- sélection Sonnet / Opus / Haiku ----------

def test_sonnet_daily_opus_deep_and_voice_haiku(monkeypatch):
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ok"))
    # tâche quotidienne → Sonnet 5.5
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert vibecode.calls[-1][1]["model"] == "claude-sonnet-5-5" == settings.vibecode_sonnet_model
    assert res.provider == "vibecode" and res.model == "claude-sonnet-5-5"
    # raisonnement profond (✦) → Opus 5.5
    res = ai.chat_complete([{"role": "user", "content": "q"}], deep=True)
    assert vibecode.calls[-1][1]["model"] == "claude-opus-5-5" == settings.vibecode_opus_model
    assert res.model == "claude-opus-5-5"
    # voix (modèle rapide demandé explicitement) → Haiku Vibecode
    res = ai.chat_complete([{"role": "user", "content": "q"}], model=settings.anthropic_voice_model)
    assert vibecode.calls[-1][1]["model"] == "claude-haiku-4-5" == settings.vibecode_haiku_model
    assert res.model == "claude-haiku-4-5"


# ---------- outils et streaming ----------

def test_vibecode_tools_loop(monkeypatch):
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    state = {"n": 0}

    def reply(kind, kw):
        state["n"] += 1
        if state["n"] == 1:
            tool = _NS(type="tool_use", name="get_prices", id="t1", input={"sku": "BA13"})
            return _NS(content=[tool], stop_reason="tool_use", model="m", usage=_usage())
        return _resp("prix trouvés")

    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, reply)
    seen = []

    def handler(name, args):
        seen.append((name, args))
        return {"price": 4500}

    tools = [{"name": "get_prices", "description": "prix", "input_schema": {"type": "object"}}]
    res = ai.chat_complete([{"role": "user", "content": "prix BA13 ?"}], tools=tools, tool_handler=handler)
    assert res.available and res.text == "prix trouvés" and res.provider == "vibecode"
    assert seen == [("get_prices", {"sku": "BA13"})]
    assert vibecode.calls[0][1]["tools"][0]["name"] == "get_prices"
    second = vibecode.calls[1][1]                               # le résultat de l'outil repart dans la conversation
    assert second["messages"][-1]["role"] == "user"
    assert second["messages"][-1]["content"][0]["type"] == "tool_result"


def test_vibecode_streaming(monkeypatch):
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("bonjour"))
    events = []
    token = ai.STREAM_CB.set(lambda ev: events.append(ev))
    try:
        res = ai.chat_complete([{"role": "user", "content": "q"}])
    finally:
        ai.STREAM_CB.reset(token)
    assert res.available and res.text == "bonjour"
    kinds = [e["t"] for e in events]
    assert kinds[0] == "reset" and "delta" in kinds             # flux en direct, comme Claude
    assert any(c[0] == "stream" for c in vibecode.calls)


def test_vibecode_degrades_to_minimal_request_when_options_rejected(monkeypatch):
    """Si le relais refuse une option avancée (tools/effort) : UN seul réessai en requête minimale, pas de boucle."""
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    state = {"n": 0}

    def reply(kind, kw):
        state["n"] += 1
        if state["n"] == 1 and ("tools" in kw or "output_config" in kw):
            raise _err(anthropic.BadRequestError, 400, "output_config not supported")
        return _resp("ok minimal")

    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, reply)
    tools = [{"name": "get_prices", "description": "d", "input_schema": {"type": "object"}}]   # outil en lecture seule (SAFE_TOOLS)
    res = ai.chat_complete([{"role": "user", "content": "q"}], tools=tools, tool_handler=lambda n, a: {})
    assert res.available and res.text == "ok minimal"
    assert len(vibecode.calls) == 2                             # exactement un réessai interne
    assert "tools" not in vibecode.calls[1][1] and "output_config" not in vibecode.calls[1][1]


def test_vibecode_receives_only_readonly_tools(monkeypatch):
    """Le relais n'expose que les outils en lecture seule (agents.SAFE_TOOLS), jamais les outils d'écriture."""
    from app import agents
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ok"))
    safe_name = sorted(agents.SAFE_TOOLS)[0]
    tools = [
        {"name": safe_name, "description": "lecture", "input_schema": {"type": "object"}},
        {"name": "create_quote", "description": "écriture", "input_schema": {"type": "object"}},   # NON sûr
        {"name": "revise_document", "description": "écriture", "input_schema": {"type": "object"}},  # NON sûr
    ]
    res = ai.chat_complete([{"role": "user", "content": "q"}], tools=tools, tool_handler=lambda n, a: {})
    assert res.available
    sent = vibecode.calls[-1][1].get("tools") or []
    assert [t["name"] for t in sent] == [safe_name]             # seul l'outil en lecture seule est transmis


def test_vibecode_without_readonly_tools_gets_no_tools(monkeypatch):
    """Si aucun outil demandé n'est en lecture seule, le relais reçoit une requête sans outil du tout."""
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("ok"))
    tools = [{"name": "create_quote", "description": "écriture", "input_schema": {"type": "object"}}]
    res = ai.chat_complete([{"role": "user", "content": "q"}], tools=tools, tool_handler=lambda n, a: {})
    assert res.available
    assert "tools" not in vibecode.calls[-1][1]                 # aucun outil d'écriture exposé au relais


def test_vibecode_tool_handler_blocks_unsafe_tools(monkeypatch):
    """Défense en profondeur : le relais appelle un outil NON sûr (nom inventé, non déclaré) →
    le handler d'origine n'est PAS exécuté ; le modèle reçoit {« error »: « outil non autorisé »}."""
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    state = {"n": 0}

    def reply(kind, kw):
        state["n"] += 1
        if state["n"] == 1:
            tool = _NS(type="tool_use", name="create_quote", id="t1", input={"client": "X"})   # NON sûr, non déclaré
            return _NS(content=[tool], stop_reason="tool_use", model="m", usage=_usage())
        if state["n"] == 2:
            tool = _NS(type="tool_use", name="get_prices", id="t2", input={"sku": "BA13"})    # sûr (SAFE_TOOLS)
            return _NS(content=[tool], stop_reason="tool_use", model="m", usage=_usage())
        return _resp("fin")

    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, reply)
    executed = []

    def handler(name, args):
        executed.append(name)
        return {"ok": True}

    tools = [{"name": "get_prices", "description": "lecture", "input_schema": {"type": "object"}}]
    res = ai.chat_complete([{"role": "user", "content": "fais un devis"}], tools=tools, tool_handler=handler)
    assert res.available and res.text == "fin"
    assert executed == ["get_prices"]                            # l'outil non sûr n'a JAMAIS été exécuté
    # résultats renvoyés au modèle : un message « user » par tour d'outils
    results = vibecode.calls[1][1]["messages"][-1]["content"] + vibecode.calls[2][1]["messages"][-1]["content"]
    by_id = {r["tool_use_id"]: r for r in results}
    assert "outil non autorisé" in by_id["t1"]["content"] and by_id["t1"].get("is_error")   # refusé, signalé en erreur
    assert '"ok"' in by_id["t2"]["content"]                      # l'outil sûr s'exécute normalement


# ---------- refroidissement d'Anthropic (anti-boucle) ----------

def test_claude_cooled_down_after_credit_exhausted(monkeypatch):
    """Crédit épuisé (402) + Vibecode configuré : Anthropic est refroidi, les messages suivants vont au relais."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    claude = _install(monkeypatch, ai.ClaudeAIProvider,
                      lambda kind, kw: _err(anthropic.APIStatusError, 402, "credit balance too low"))
    vibecode = _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("vibecode"))
    r1 = ai.chat_complete([{"role": "user", "content": "q1"}])
    assert r1.provider == "vibecode"
    n_claude = len(claude.calls)
    r2 = ai.chat_complete([{"role": "user", "content": "q2"}])
    assert r2.provider == "vibecode"
    assert len(claude.calls) == n_claude                        # Anthropic non réessayé pendant le refroidissement
    assert len(vibecode.calls) == 2
    monkeypatch.setattr(settings, "ai_quota_cooldown_s", 0)     # refroidissement désactivé : Anthropic réessayé
    ai.chat_complete([{"role": "user", "content": "q3"}])
    assert len(claude.calls) > n_claude


def test_cooldown_only_applies_when_vibecode_configured(monkeypatch):
    """Sans relais Vibecode configuré, le refroidissement ne s'applique PAS : Claude est toujours essayé."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    claude = _install(monkeypatch, ai.ClaudeAIProvider,
                      lambda kind, kw: _err(anthropic.APIStatusError, 402, "credit balance too low"))
    r1 = ai.chat_complete([{"role": "user", "content": "q1"}])
    assert not r1.available                                     # pas de relais, pas de secours local : échec honnête
    n = len(claude.calls)
    ai.chat_complete([{"role": "user", "content": "q2"}])
    assert len(claude.calls) > n                                # Claude réessayé : sans Vibecode, pas de refroidissement


def test_429_does_not_cooldown_claude(monkeypatch):
    """Un 429 est transitoire : il bascule vers Vibecode mais ne refroidit PAS Anthropic."""
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk")
    claude = _install(monkeypatch, ai.ClaudeAIProvider,
                      lambda kind, kw: _err(anthropic.RateLimitError, 429, "rate limit"))
    _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("vibecode"))
    r1 = ai.chat_complete([{"role": "user", "content": "q1"}])
    assert r1.provider == "vibecode"                            # bascule OK sur 429
    n = len(claude.calls)
    r2 = ai.chat_complete([{"role": "user", "content": "q2"}])
    assert len(claude.calls) > n                                # 429 = temporaire : Claude est réessayé
    assert r2.provider == "vibecode"


# ---------- sécurité ----------

def test_vibecode_error_never_leaks_the_key(monkeypatch):
    monkeypatch.setattr(settings, "vibecode_api_key", "vk-secret")
    _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: RuntimeError("vk-secret leaked?"))
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert not res.available and "vk-secret" not in res.error


def test_no_api_key_nothing_is_sent_anywhere(monkeypatch):
    """Sans clé Vibecode, aucune requête ne sort (health seule, aucun appel)."""
    res = ai.chat_complete([{"role": "user", "content": "q"}])
    assert not res.available and res.provider == "none"


# ---------- compteur d'usage ----------

def test_usage_cost_uses_vibecode_prices():
    from app import usage
    rows = [{"input": 1_000_000, "output": 0, "cache_read": 0, "cache_write": 0, "web": 0}]
    _, usd_claude, known_claude = usage.cost_of("claude-sonnet-5-5", rows, provider="claude")
    _, usd_vibecode, known_vibecode = usage.cost_of("claude-sonnet-5-5", rows, provider="vibecode")
    assert known_claude and known_vibecode
    assert usd_claude == 2.0                                    # tarif public Anthropic
    assert usd_vibecode == 0.20                                 # tarif relais Vibecode (indicatif)
    assert usd_vibecode < usd_claude                            # le relais est moins cher : pas de tarif Anthropic appliqué


# ---------- API de bout en bout (mémoire conservée, bascule réelle) ----------

def test_chat_api_failover_to_vibecode_and_usage_recorded(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk-test")
    _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: _err(anthropic.RateLimitError, 429, "quota"))
    _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _resp("réponse du relais Vibecode"))
    r = client.post("/api/chat", json={"message": "Quelle plaque pour une salle de bain ?"}).json()
    assert "réponse du relais Vibecode" in r["message"]["content"]
    summary = client.get("/api/usage").json()
    row = next((m for m in summary["par_modele"] if m["model"] == settings.vibecode_sonnet_model), None)
    assert row is not None and row["messages"] >= 1             # usage enregistré sous le modèle réellement utilisé


def test_chat_api_validated_memory_survives_when_both_cloud_apis_fail(client, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "vibecode_api_key", "vk-test")
    # 1) Anthropic répond, le patron valide la réponse (👍) : elle devient un savoir
    _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: _resp("Le BA13 hydrofuge se pose en salle de bain."))
    r = client.post("/api/chat", json={"message": "Quelle plaque pour une salle de bain ?"}).json()
    assert "hydrofuge" in r["message"]["content"]
    assert client.post(f"/api/messages/{r['message']['id']}/validate").status_code == 200
    # 2) les deux API cloud tombent (quota Anthropic + panne Vibecode), aucun secours local configuré
    _install(monkeypatch, ai.ClaudeAIProvider, lambda kind, kw: _err(anthropic.RateLimitError, 429, "quota"))
    _install(monkeypatch, ai.VibecodeAIProvider, lambda kind, kw: _err(anthropic.InternalServerError, 500, "down"))
    r2 = client.post("/api/chat", json={"message": "Quelle plaque pour une salle de bain ?"}).json()
    assert "déjà validée" in r2["message"]["content"]           # le savoir validé répond, mémoire conservée
    assert "hydrofuge" in r2["message"]["content"]
