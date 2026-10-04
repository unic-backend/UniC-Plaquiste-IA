"""Mémoire durable : l'assistant garde ce que le patron lui apprend, d'une conversation à l'autre.

Principes (repris de l'expérience du projet ARENA du même propriétaire, réécrits pour UniC) :
1. Une supposition ne devient JAMAIS un fait toute seule : ce que l'IA déduit ou ce qui est importé reste
   « supposition non confirmée » jusqu'à ce que le patron confirme.
2. Dire deux fois la même chose = un souvenir compté deux fois, pas deux souvenirs. Rien n'est supprimé en silence.
3. Deux souvenirs qui se contredisent sur un chiffre sont RAPPORTÉS, jamais arbitrés : le patron tranche.
4. Un secret (clé, mot de passe, carte) n'est jamais mémorisé, même sur ordre.
5. Retrouver sans tout charger : budget dur, plusieurs signaux (mots, importance, récence, date évoquée), explication.
6. L'état de la mémoire se mesure (persistance du disque, conflits) : il ne se suppose pas.
"""
from __future__ import annotations

from contextvars import ContextVar

import io
import json
import logging
import math
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import ai, retrieval, trust
from app.config import settings
from app.models import Conversation, Memory, Message

logger = logging.getLogger("unic.memory")
PROCESS_START = datetime.now(timezone.utc)

MAX_TEXT = 500
MAX_ITEMS = 400
BLOCK_CHARS = 3500
HALF_LIFE_DAYS = 90.0
THRESHOLD = 0.1
WEIGHTS = {"match": 0.5, "importance": 0.2, "recency": 0.15, "temporal": 0.15}
ALWAYS_ON_SHARE = 0.4          # part du budget réservée aux règles/préférences du patron (toujours utiles)
ALWAYS_ON_IMPORTANCE = 0.85
KINDS = ("fact", "preference", "correction", "task")
NATURES = ("fact", "preference", "inference", "temporary")
TEMP_HOURS = 36
MARK_GUESS = "[supposition non confirmée]"

REMEMBER_RE = re.compile(
    r"^\s*(?:retiens|retenez|souviens[- ]toi|rappelle[- ]toi|n'oublie pas|notez? bien|notez? que)\s*(?:que|qu'|:)?\s*(.+)$",
    re.I | re.S,
)
# Classement par motifs (accents ignorés), jamais par un modèle : même verdict à chaque exécution.
_TASK = re.compile(r"\b(?:rappelle[- ]moi|n'?oublie\s+pas|pense\s+a|il\s+faudra|a\s+faire|plus\s+tard|la\s+semaine\s+prochaine)\b")
_PREF = re.compile(r"\b(?:je\s+(?:veux|voudrais|prefere|aime|deteste|n'?aime\s+pas)|j'?aimerais|il\s+faut\s+que\s+tu|ne\s+fais\s+plus|arrete\s+de)\b")
_RULE = re.compile(r"\b(?:toujours|jamais|d'?habitude|en\s+general|par\s+defaut|la\s+regle|mon\s+tarif|mes\s+tarifs|je\s+facture|je\s+fais\s+toujours)\b")
_TEMP = re.compile(r"\b(?:aujourd'?hui|ce\s+soir|ce\s+matin|demain|cette\s+semaine|en\s+ce\s+moment|pour\s+l'?instant)\b")
_BANAL = re.compile(r"^\W*(?:bonjour|bonsoir|salut|merci|ok|okay|oui|non|d'?accord|c'?est\s+bon|vas[- ]?y|parfait|super|nickel|bien)\W*$")
IMPORTANCE = {"rule": 0.9, "preference": 0.85, "task": 0.8, "ordinary": 0.5, "temporary": 0.4}


class MemoryRefused(ValueError):
    """Souvenir refusé, avec la raison à dire au patron."""


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify(text: str) -> tuple[str, str, float, int | None]:
    """(kind, nature, importance, durée de validité en heures) d'une phrase du patron."""
    t = retrieval.normalize(text)
    if _TEMP.search(t) and not _RULE.search(t):
        return ("fact", "temporary", IMPORTANCE["temporary"], TEMP_HOURS)
    if _TASK.search(t):
        return ("task", "fact", IMPORTANCE["task"], None)
    if _PREF.search(t):
        return ("preference", "preference", IMPORTANCE["preference"], None)
    if _RULE.search(t):
        return ("fact", "fact", IMPORTANCE["rule"], None)
    return ("fact", "fact", IMPORTANCE["ordinary"], None)


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", retrieval.normalize(text)).strip()


def _similar(a: str, b: str) -> bool:
    """Même phrase, ou presque (Jaccard sur les mots utiles) : « Je facture 30 % d'acompte » ≈ « j'facture 30% d'acompte »."""
    if _key(a) == _key(b):
        return True
    wa, wb = retrieval.useful_words(a), retrieval.useful_words(b)
    if len(wa) < 3 or len(wb) < 3:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.85


def add(db: Session, text: str, kind: str | None = None, source: str = "user", pinned: bool = False,
        nature: str | None = None, importance: float | None = None) -> Memory | None:
    """Ajoute un souvenir. Rend None si trop court ou déjà connu (alors compté, pas dupliqué).

    Lève MemoryRefused pour un secret. Un souvenir déduit (auto) ou importé est une SUPPOSITION ; redit par le
    patron, il devient un fait confirmé."""
    text = " ".join((text or "").split())[:MAX_TEXT]
    if len(text) < 5 or _BANAL.match(retrieval.normalize(text)):
        return None
    secret = trust.find_secret(text)
    if secret:
        raise MemoryRefused(f"Je ne mémorise pas les secrets ({secret}). Garde-le dans un gestionnaire de mots de passe.")
    c_kind, c_nature, c_imp, ttl = classify(text)
    stated = source == "user"
    kind = kind if kind in KINDS else c_kind
    if nature not in NATURES:
        if stated:
            nature = c_nature
        elif source == "import":
            nature = "inference"   # un export ancien : jamais « valable maintenant »
        else:
            nature = "temporary" if c_nature == "temporary" else "inference"
    importance = c_imp if importance is None else max(0.0, min(1.0, importance))
    now = _now()

    for m in db.query(Memory).filter(Memory.state == "active").all():
        if _similar(m.text, text):
            m.occurrences = (m.occurrences or 1) + 1
            m.last_seen = now
            if stated and m.nature == "inference":
                m.nature, m.source = c_nature if c_nature != "temporary" else "fact", "user"   # confirmé par le patron
                m.pinned = m.pinned or pinned
                return m
            if pinned and not m.pinned:
                m.pinned = True
            return None

    if db.query(Memory).filter(Memory.state == "active").count() >= MAX_ITEMS:
        old = (db.query(Memory).filter(Memory.state == "active", Memory.pinned.is_(False))
               .order_by(Memory.importance, Memory.created_at).first())
        if old:
            old.state = "archived"   # archivé, jamais supprimé en silence
    m = Memory(text=text, kind=kind, source=source if source in ("user", "auto", "import") else "user", pinned=pinned,
               nature=nature, importance=importance, occurrences=1, last_seen=now,
               expires_at=now + timedelta(hours=ttl) if (nature == "temporary" and ttl) else None)
    db.add(m)
    db.flush()
    return m


_QUOTES = " \t\r\n«»\"“”„‘’'"


def parse_remember(text: str) -> str | None:
    """« Retiens que X » → X, sans guillemets ni ponctuation de bord copiés avec la phrase."""
    m = REMEMBER_RE.match((text or "").lstrip(_QUOTES))
    if not m:
        return None
    return m.group(1).strip(_QUOTES + ".!;,") or None


# ---------- décisions du patron ----------

def decide(db: Session, mid: str, action: str) -> Memory | None:
    """confirm : la supposition devient un fait · reject : plus jamais rendue · archive · pin / unpin."""
    m = db.get(Memory, mid)
    if m is None:
        return None
    if action == "confirm":
        m.nature = "preference" if m.kind == "preference" else "fact"
        m.source, m.state = "user", "active"
    elif action == "reject":
        m.state = "rejected"
    elif action == "archive":
        m.state = "archived"
    elif action == "restore":
        m.state = "active"
    elif action == "pin":
        m.pinned = True
    elif action == "unpin":
        m.pinned = False
    else:
        raise ValueError("Action inconnue")
    return m


# ---------- retrouver ----------

@dataclass
class Hit:
    memory: Memory
    score: float
    signals: dict = field(default_factory=dict)
    always: bool = False

    def why(self) -> str:
        if self.always:
            return "toujours utile (règle ou préférence du patron)"
        parts = [f"{k} {v:.2f}" for k, v in self.signals.items() if v > 0]
        return f"score {self.score:.2f} ({', '.join(parts) or 'aucun signal'})"


def _active(db: Session, now: datetime) -> list[Memory]:
    out = []
    for m in db.query(Memory).filter(Memory.state == "active").all():
        exp = _aware(m.expires_at)
        if exp is not None and exp <= now:
            continue
        out.append(m)
    return out


def _recency(m: Memory, now: datetime) -> float:
    created = _aware(m.created_at) or now
    return math.pow(0.5, max(0.0, (now - created).total_seconds() / 86400.0) / HALF_LIFE_DAYS)


def render_line(m: Memory, conflict: str = "") -> str:
    prefix = f"{MARK_GUESS} " if m.nature == "inference" else ""
    tail = f" (dit {m.occurrences} fois)" if (m.occurrences or 1) > 1 else ""
    exp = _aware(m.expires_at)
    if exp is not None:
        tail += f" (valable jusqu'au {exp.strftime('%d/%m')})"
    if conflict:
        tail += f" ⚠ CONTREDIT par « {conflict[:80]} » : ne tranche pas, demande au patron"
    return f"- ({m.kind}) {prefix}{m.text}{tail}"


def retrieve(db: Session, query: str, budget: int = BLOCK_CHARS, now: datetime | None = None) -> list[Hit]:
    """Les souvenirs à rendre : toujours-utiles d'abord, puis les plus pertinents, dans un budget DUR."""
    now = now or _now()
    words = retrieval.useful_words(query)
    window = retrieval.evoked_window(query, now)
    active = _active(db, now)
    hits: list[Hit] = []
    used = 0
    always = sorted((m for m in active if m.pinned or (m.nature in ("fact", "preference") and (m.importance or 0) >= ALWAYS_ON_IMPORTANCE)),
                    key=lambda m: (-(m.importance or 0), _aware(m.created_at) or now), reverse=False)
    for m in always:
        cost = len(render_line(m)) + 1
        if used + cost > budget * ALWAYS_ON_SHARE:
            continue
        hits.append(Hit(m, 1.0, {"importance": m.importance or 0}, always=True))
        used += cost
    chosen = {h.memory.id for h in hits}
    scored = []
    for m in active:
        if m.id in chosen:
            continue
        mw = retrieval.useful_words(m.text)
        match = len(words & mw) / len(words) if words else 0.0
        created = _aware(m.created_at) or now
        temporal = 1.0 if (window and window[0] <= created <= window[1]) else 0.0
        sig = {"match": match, "importance": m.importance or 0.0, "recency": _recency(m, now), "temporal": temporal}
        score = sum(WEIGHTS[k] * v for k, v in sig.items())
        if score >= THRESHOLD and (match > 0 or temporal > 0):
            scored.append(Hit(m, score, sig))
    scored.sort(key=lambda h: h.score, reverse=True)
    for h in scored:
        cost = len(render_line(h.memory)) + 1
        if used + cost > budget:
            continue
        hits.append(h)
        used += cost
    return hits


# ---------- contradictions ----------

_THOUSANDS = re.compile(r"(?<=\d)[\s .,](?=\d{3}(?!\d))")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def numbers(text: str) -> tuple[str, ...]:
    out = []
    for raw in _NUMBER.findall(_THOUSANDS.sub("", text)):
        v = raw.replace(",", ".")
        if "." in v:
            v = v.rstrip("0").rstrip(".")
        out.append(v.lstrip("0") or "0")
    return tuple(out)


def _subject(text: str) -> frozenset:
    return frozenset(w for w in retrieval.useful_words(text) if not w.isdigit())


def conflicts(db: Session) -> list[dict]:
    """Même sujet, nombres différents (prix, surface, délai). Rapporté, jamais arbitré.

    Portée : seules les divergences NUMÉRIQUES sont vues ; une négation ou un sens contraire ne le sont pas."""
    items = [(m, _subject(m.text), numbers(m.text)) for m in _active(db, _now())
             if m.nature != "temporary" and m.kind != "task"]
    out = []
    for i, (a, sa, na) in enumerate(items):
        if not na:
            continue
        for b, sb, nb in items[i + 1:]:
            if not nb or set(na) == set(nb):
                continue
            common = sa & sb
            if len(common) < 2:
                continue
            out.append({"a": {"id": a.id, "text": a.text, "nature": a.nature}, "b": {"id": b.id, "text": b.text, "nature": b.nature},
                        "sujet": sorted(common),
                        "raison": f"Même sujet ({', '.join(sorted(common))}) et nombres différents : "
                                  f"{', '.join(n for n in na if n not in nb) or '—'} contre {', '.join(n for n in nb if n not in na) or '—'}."})
    return out


def block(db: Session, query: str = "", limit_chars: int = BLOCK_CHARS) -> str:
    """Texte injecté dans le prompt : ce que le patron a appris à l'IA, avec nature et conflits."""
    hits = retrieve(db, query, limit_chars)
    if not hits:
        return ""
    clash: dict[str, str] = {}
    for c in conflicts(db):
        clash.setdefault(c["a"]["id"], c["b"]["text"])
        clash.setdefault(c["b"]["id"], c["a"]["text"])
    lines = [render_line(h.memory, clash.get(h.memory.id, "")) for h in hits]
    head = ("MÉMOIRE UNIC (ce que le patron t'a appris). Les lignes « supposition non confirmée » sont des déductions : "
            "ne les présente jamais comme des faits. Une ligne CONTREDIT = deux versions : demande laquelle est juste.")
    return head + "\n" + "\n".join(lines)


# ---------- échanges passés : « on en avait parlé il y a trois jours » ----------

def recall_past(db: Session, query: str, exclude_conversation_id: str | None = None, budget: int = 2500,
                max_lines: int = 6, now: datetime | None = None) -> str:
    """Passages pertinents d'AUTRES conversations (mots communs + date évoquée). Vide si rien de net."""
    now = now or _now()
    window = retrieval.evoked_window(query, now)
    q = db.query(Message, Conversation.title).join(Conversation, Conversation.id == Message.conversation_id) \
        .filter(Message.role.in_(("user", "assistant")))
    if exclude_conversation_id:
        q = q.filter(Message.conversation_id != exclude_conversation_id)
    rows = q.order_by(Message.created_at.desc()).limit(800).all()
    if not rows:
        return ""
    records = [retrieval.Record(m.id, (m.content or "")[:1200], title) for m, title in rows]
    by_id = {m.id: (m, title) for m, title in rows}
    ranked = retrieval.bm25(query, records)
    picked: list[str] = []
    if ranked:
        top = ranked[0][1]
        picked = [i for i, s in ranked if s >= 0.35 * top][:max_lines]
    if window:
        in_window = [m.id for m, _ in rows if (d := _aware(m.created_at)) and window[0] <= d <= window[1]]
        for i in in_window[:max_lines]:
            if i not in picked and len(picked) < max_lines:
                picked.append(i)
    lines, used = [], 0
    for i in picked:
        m, title = by_id[i]
        who = "Patron" if m.role == "user" else "JARVIS"
        d = _aware(m.created_at)
        line = f"- [{d.strftime('%d/%m') if d else '?'} · « {(title or '')[:40]} »] {who} : {' '.join((m.content or '').split())[:280]}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    return ("ÉCHANGES PASSÉS PERTINENTS (autres conversations ; ils peuvent contenir des erreurs : la MÉMOIRE et la BASE UNIC priment) :\n"
            + "\n".join(lines))


# ---------- état mesuré ----------

def _device(path) -> int:
    return os.stat(path).st_dev


def state_report(db: Session) -> dict:
    now = _now()
    all_rows = db.query(Memory).all()
    by_nature: dict[str, int] = {}
    for m in all_rows:
        if m.state == "active":
            by_nature[m.nature] = by_nature.get(m.nature, 0) + 1
    oldest_rows = [d for d in (_aware(r.created_at) for r in all_rows) if d]
    old_conv = db.query(Conversation.created_at).order_by(Conversation.created_at).first() if hasattr(Conversation, "created_at") else None
    first = min([d for d in oldest_rows + ([_aware(old_conv[0])] if old_conv and old_conv[0] else []) if d], default=None)
    data = settings.data_path
    try:
        separate = _device(data) != _device("/")
    except OSError:
        separate = False
    survived = None if first is None else first < PROCESS_START - timedelta(seconds=60)
    warning = None
    if not separate and os.environ.get("RENDER"):
        warning = "Aucun disque persistant détecté : tes souvenirs seront EFFACÉS au prochain redéploiement. Ajoute un disque sur /data."
    elif survived is False and not separate:
        warning = "Les données sont toutes plus récentes que le dernier démarrage : si tu avais des souvenirs avant, ils ont peut-être été perdus."
    return {
        "actifs": sum(by_nature.values()), "par_nature": by_nature,
        "a_confirmer": by_nature.get("inference", 0),
        "rejetes": sum(1 for m in all_rows if m.state == "rejected"), "archives": sum(1 for m in all_rows if m.state == "archived"),
        "taches": sum(1 for m in all_rows if m.kind == "task" and m.state == "active"),
        "conflits": len(conflicts(db)), "le_plus_ancien": first.isoformat() if first else None,
        "disque_separe": separate, "a_survecu_a_un_redemarrage": survived, "avertissement": warning,
        "recherche": "par mots (sans calcul de sens)", "portee_conflits": "divergences numériques uniquement",
    }


# ---------- règles du patron enregistrées une fois pour toutes ----------

OWNER_RULES_V1 = (
    "Une barre (fourrure, montant, rail, cornière) mesure 2,90 m. Une barre n'est pas un paquet : ne jamais confondre ni convertir l'un en l'autre.",
    "Une barre de fourrure coûte 1 200 FCFA (c'est le prix d'une barre, pas d'un paquet).",
    "Plaques de plâtre : par défaut 2 m de long sur 1,20 m de large. Seulement si le patron précise « 2,50 » : 2,50 m de long sur 1,20 m de large.",
    "Vis : 25 mm par défaut ; 35 mm uniquement si le patron le dit.",
    "Médina est un lieu (quartier de Dakar), pas un client ni un article.",
)


OWNER_RULES_V2: tuple = ()   # remplacée par V3 (le prix de 6 500 était celui de la plaque de 2,50 m, pas de 2 m)
OWNER_RULES_V3 = (
    "Prix des plaques BA13 : standard 2 m × 1,20 m = 4 500 FCFA ; standard 2,50 m × 1,20 m = 6 500 FCFA ; hydrofuge 2,50 m × 1,20 m = 8 000 FCFA. "
    "Chaque taille de plaque a son prix : ne jamais appliquer le prix de l'une à l'autre.",
)
OWNER_RULES_V4 = (
    "Plaques : si le patron donne un nombre de plaques SANS préciser la taille (« 20 plaques »), c'est la plaque de 2 m (standard 4 500 FCFA, "
    "hydrofuge 6 000 FCFA) : choix automatique, ne pas redemander la taille. La plaque de 2,50 m (6 500 ; hydrofuge 8 000) seulement s'il dit « 2,50 ». "
    "C'est le patron qui choisit la plaque : ne jamais en choisir une autre de ton côté.",
)
_RULE_SETS = {"v1": OWNER_RULES_V1, "v2": OWNER_RULES_V2, "v3": OWNER_RULES_V3, "v4": OWNER_RULES_V4}


def seed_owner_rules(db: Session) -> int:
    """Pose une seule fois chaque série de règles énoncées par le patron. Supprimées ensuite, elles ne reviennent pas."""
    from app.models import AppSetting

    n = 0
    for version, rules in _RULE_SETS.items():
        flag = f"seed_owner_rules_{version}"
        if db.get(AppSetting, flag):
            continue
        if version == "v4":   # la règle de prix précédente ignorait l'hydrofuge 2 m : remplacée
            for m in db.query(Memory).filter(Memory.state == "active", Memory.text.like("Prix des plaques BA13 : standard 2 m%")):
                m.state = "archived"
            rules = rules + (
                "Prix des plaques BA13 : standard 2 m × 1,20 m = 4 500 FCFA ; hydrofuge 2 m = 6 000 FCFA ; standard 2,50 m = 6 500 FCFA ; "
                "hydrofuge 2,50 m = 8 000 FCFA. Chaque taille a son prix : ne jamais appliquer le prix de l'une à l'autre.",)
        if version == "v3":   # la règle de prix erronée de la version précédente est archivée
            for m in db.query(Memory).filter(Memory.state == "active", Memory.text.like("Prix d'une plaque BA13 standard : 6 500%")):
                m.state = "archived"
        for text in rules:
            try:
                if add(db, text, kind="preference", source="user", pinned=True):
                    n += 1
            except MemoryRefused:
                continue
        db.add(AppSetting(key=flag, value="1"))
        db.commit()
    return n


# ---------- apprentissage automatique (suppositions) ----------

# Textes à analyser APRÈS l'envoi de la réponse (l'extraction est un second appel à l'IA : il ne doit pas faire attendre le patron).
AFTER_REPLY: ContextVar = ContextVar("unic_after_reply", default=None)


def defer_extract(db: Session, user_text: str) -> None:
    pending = AFTER_REPLY.get()
    if pending is None:
        extract_and_store(db, user_text)  # pas d'envoi différé possible (appel direct) : tout de suite
    else:
        pending.append(user_text)


def extract_in_background(user_text: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        extract_and_store(db, user_text)
        db.commit()
    except Exception as exc:  # jamais bloquer ni faire échouer quoi que ce soit
        logger.debug("extraction mémoire différée impossible : %s", exc)
    finally:
        db.close()


def extract_and_store(db: Session, user_text: str) -> list[str]:
    """Extraction depuis un message du patron : des SUPPOSITIONS à confirmer, jamais des faits. Silencieuse en cas d'échec."""
    if len(user_text) < 30 or not ai.provider_chain() or trust.find_secret(user_text):
        return []
    try:
        res = ai.chat_complete([
            {"role": "system", "content": (
                "Extrais du message du patron les faits DURABLES qu'il énonce lui-même : préférences, "
                "prix, noms de clients/fournisseurs, méthodes, corrections d'une erreur de l'assistant. "
                "N'invente rien, ne déduis rien, ignore les questions et les calculs ponctuels. "
                'Réponds UNIQUEMENT par un tableau JSON de phrases courtes, ou []. Exemple : ["Le BA13 hydrofuge se pose en salle de bain"]'
            )},
            {"role": "user", "content": user_text[:2000]},
        ], max_tokens=300, effort="low")
        m = re.search(r"\[.*\]", res.text or "", re.S)
        items = json.loads(m.group(0)) if m else []
    except Exception as exc:  # jamais bloquer la conversation
        logger.debug("extraction mémoire impossible : %s", exc)
        return []
    saved = []
    for it in items[:5]:
        if isinstance(it, str):
            kind = "correction" if re.search(r"\b(non|erreur|faux|corrige)\b", user_text, re.I) else None
            try:
                if add(db, it, kind=kind, source="auto"):
                    saved.append(it)
            except MemoryRefused:
                continue
    return saved


# ---------- importer ChatGPT / Claude / texte brut ----------

class UnknownImport(ValueError):
    pass


def _user_texts_from_json(data) -> list[str]:
    out: list[str] = []
    convs = data if isinstance(data, list) else [data]
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        if "mapping" in conv:   # export ChatGPT
            for node in (conv.get("mapping") or {}).values():
                msg = (node or {}).get("message") or {}
                if (msg.get("author") or {}).get("role") == "user":
                    parts = (msg.get("content") or {}).get("parts") or []
                    out.extend(p for p in parts if isinstance(p, str))
        elif "chat_messages" in conv:   # export Claude
            for msg in conv.get("chat_messages") or []:
                if msg.get("sender") in ("human", "user"):
                    text = msg.get("text") or " ".join(b.get("text", "") for b in (msg.get("content") or []) if isinstance(b, dict))
                    out.append(text)
    return out


def candidates_from_export(raw: bytes, filename: str = "") -> list[str]:
    """Phrases du patron qui ressemblent à une règle, une préférence ou une tâche. Jamais exécutées, jamais des faits."""
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
                if name is None:
                    raise UnknownImport("Archive sans conversations.json.")
                raw = z.read(name)
        except zipfile.BadZipFile:
            raise UnknownImport("Archive illisible.")
    text = raw.decode("utf-8", errors="replace")
    texts: list[str]
    try:
        texts = _user_texts_from_json(json.loads(text))
    except json.JSONDecodeError:
        if filename.lower().endswith(".json"):
            raise UnknownImport("JSON illisible.")
        texts = text.splitlines()   # texte brut : une idée par ligne
    found: list[str] = []
    seen: set[str] = set()
    for chunk in texts:
        for sentence in re.split(r"(?<=[.!?\n])\s+", chunk or ""):
            s = " ".join(sentence.split())
            n = retrieval.normalize(s)
            if not (20 <= len(s) <= 300) or s.endswith("?"):
                continue
            if not (_RULE.search(n) or _PREF.search(n) or _TASK.search(n) or REMEMBER_RE.match(s)):
                continue
            if _TEMP.search(n):
                continue   # « demain », « ce soir » dans un vieil export : périmé
            if trust.find_secret(s) or trust.inspect(s):
                continue
            k = _key(s)
            if k not in seen:
                seen.add(k)
                found.append(s)
        if len(found) >= 200:
            break
    return found


def import_candidates(db: Session, texts: list[str]) -> dict:
    added = skipped = 0
    for t in texts:
        try:
            if add(db, t, source="import"):
                added += 1
            else:
                skipped += 1
        except MemoryRefused:
            skipped += 1
    return {"ajoutes": added, "ignores": skipped, "note": "Importés comme suppositions : confirme celles qui sont justes."}
