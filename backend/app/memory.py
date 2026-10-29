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

from sqlalchemy import or_
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
        nature: str | None = None, importance: float | None = None, subject: str = "") -> Memory | None:
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

    subject = (subject or "")[:120]
    for m in db.query(Memory).filter(Memory.state == "active", Memory.subject == subject).all():   # même phrase pour un autre client = autre souvenir
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

    if db.query(Memory).filter(Memory.state == "active", Memory.subject == subject).count() >= MAX_ITEMS:
        old = (db.query(Memory).filter(Memory.state == "active", Memory.subject == subject, Memory.pinned.is_(False))
               .order_by(Memory.importance, Memory.created_at).first())
        if old:
            old.state = "archived"   # archivé, jamais supprimé en silence
    m = Memory(text=text, kind=kind, source=source if source in ("user", "auto", "import") else "user", pinned=pinned,
               nature=nature, importance=importance, occurrences=1, last_seen=now, subject=subject,
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


def _active(db: Session, now: datetime, subject: str = "") -> list[Memory]:
    """Souvenirs actifs d'UN périmètre : général (subject vide) ou un client précis. Jamais les deux mélangés."""
    out = []
    for m in db.query(Memory).filter(Memory.state == "active", Memory.subject == (subject or "")).all():
        exp = _aware(m.expires_at)
        if exp is not None and exp <= now:
            continue
        out.append(m)
    return out


def _active_all(db: Session, now: datetime) -> list[Memory]:
    out = []
    for m in db.query(Memory).filter(Memory.state == "active").all():
        exp = _aware(m.expires_at)
        if exp is None or exp > now:
            out.append(m)
    return out


def for_subject(db: Session, subject: str, limit: int = 40) -> list[Memory]:
    """Tout ce qui est retenu sur UN client/chantier (les plus récents d'abord). Vide si rien."""
    rows = _active(db, _now(), subject)
    rows.sort(key=lambda m: _aware(m.created_at) or _now(), reverse=True)
    return rows[:limit]


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
        tail += f" ⚠ CONTREDIT par « {conflict[:150]} » : ne tranche pas, demande au patron"
    return f"- ({m.kind}) {prefix}{m.text}{tail}"


def retrieve(db: Session, query: str, budget: int = BLOCK_CHARS, now: datetime | None = None, subject: str = "") -> list[Hit]:
    """Les souvenirs à rendre : toujours-utiles d'abord, puis les plus pertinents, dans un budget DUR."""
    now = now or _now()
    words = retrieval.useful_words(query)
    window = retrieval.evoked_window(query, now)
    active = _active(db, now, subject)
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


# Mots qui reviennent dans presque toutes les lignes de prix : ils ne disent PAS que deux lignes parlent de la même chose.
_GENERIC = frozenset({"fcfa", "cfa", "franc", "francs", "prix", "coute", "coutent", "paquet", "paquets", "unite", "unites", "piece", "pieces",
                      "tarif", "montant", "total", "par", "defaut", "seulement", "jamais", "toujours", "patron", "devis"})


def _subject(text: str) -> frozenset:
    return frozenset(w for w in retrieval.useful_words(text) if not w.isdigit() and w not in _GENERIC)


def conflicts(db: Session, only: set[str] | None = None) -> list[dict]:
    """Même sujet, nombres différents (prix, surface, délai). Rapporté, jamais arbitré.

    `only` : ne garde que les divergences où l'un des deux souvenirs est dans cet ensemble (le prompt n'en montre que quelques-uns :
    comparer seulement ceux-là coûte une fraction du balayage complet, qui reste quadratique).

    Portée : seules les divergences NUMÉRIQUES sont vues ; une négation ou un sens contraire ne le sont pas."""
    now = _now()
    items = [(m, _subject(m.text), numbers(m.text)) for m in _active_all(db, now)
             if m.nature != "temporary" and m.kind != "task"]
    items = [(m, sm, nm, frozenset(nm)) for m, sm, nm in items if nm]   # sans nombre, aucune divergence possible
    out = []
    for i, (a, sa, na, nsa) in enumerate(items):
        a_in = only is None or a.id in only
        for b, sb, nb, nsb in items[i + 1:]:
            if not a_in and b.id not in only:
                continue
            if a.subject != b.subject:   # deux clients différents peuvent avoir des chiffres différents : pas une contradiction
                continue
            if nsa == nsb:
                continue
            common = sa & sb
            # même CHOSE, pas seulement deux mots communs : sinon « barre mesure 2,80 m » contredirait « barre coûte 1 200 FCFA »
            if len(common) < 2 or len(common) / len(sa | sb) < 0.5:
                continue
            newer = a if (a.created_at or now) >= (b.created_at or now) else b
            out.append({"a": {"id": a.id, "text": a.text, "nature": a.nature}, "b": {"id": b.id, "text": b.text, "nature": b.nature},
                        "plus_recent": newer.id,
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

    def _other(c: dict, mine: str) -> str:   # l'AUTRE version, avec son statut : une supposition ne vaut jamais une valeur confirmée
        o = c["b"] if c["a"]["id"] == mine else c["a"]
        tag = "plus récente" if c["plus_recent"] == o["id"] else "plus ancienne"
        kind = "supposition non confirmée" if o["nature"] == "inference" else "confirmée par le patron"
        return f"{o['text']} [{tag}, {kind}]"
    for c in conflicts(db, only={h.memory.id for h in hits}):   # seuls les souvenirs montrés comptent (le balayage complet est quadratique)
        clash.setdefault(c["a"]["id"], _other(c, c["a"]["id"]))
        clash.setdefault(c["b"]["id"], _other(c, c["b"]["id"]))
    lines = [render_line(h.memory, clash.get(h.memory.id, "")) for h in hits]
    head = ("MÉMOIRE UNIC (ce que le patron t'a appris). Les lignes « supposition non confirmée » sont des déductions : "
            "ne les présente jamais comme des faits. Une ligne CONTREDIT = deux versions : une supposition, un ancien export ou un document "
            "ne remplace JAMAIS une valeur confirmée par le patron ; entre deux valeurs confirmées, cite les deux avec leur ordre et demande laquelle est juste.")
    return head + "\n" + "\n".join(lines)


# ---------- échanges passés : « on en avait parlé il y a trois jours » ----------

RECENT_SCAN = 800      # derniers messages toujours lus
SEARCH_SCAN = 3000     # recherche demandée : messages de TOUTE date (archives comprises) qui contiennent un mot de la question
RECALL_SCAN = 400      # rappel automatique à chaque message : budget plus court (le classement coûte ~0,1 s par millier de messages)
_LIKE_WORD = re.compile(r"[^\W_]{4,}")
# mots de la demande « retrouve la conversation où on a parlé de… » : ils disent qu'on cherche, pas CE qu'on cherche
_SEARCH_NOISE = frozenset(retrieval.normalize(w) for w in (
    "conversation conversations discussion discussions échange échanges message messages parlé parler parlait dit dis "
    "disais avais avait avions demande demandé est-ce retrouve retrouver cherche chercher rappelle souviens souvenir fois déjà ensemble").split())
_DATE_WORDS = frozenset("hier avant-hier avant semaine semaines derniere dernier mois annee an ans jour jours il".split())


def _like_words(query: str) -> list[tuple[str, ...]]:
    """Mots distinctifs de la question, chacun tel que tapé ET sans accents (« métré » / « metre »), pour un filtre SQL."""
    groups: list[tuple[str, ...]] = []
    for w in sorted({w.lower() for w in _LIKE_WORD.findall(query or "")}, key=lambda w: (-len(w), w)):
        n = retrieval.normalize(w)
        if n in retrieval.STOP_WORDS or n in _SEARCH_NOISE or any(n in g for g in groups):
            continue
        groups.append(tuple(dict.fromkeys((w, n))))
        if len(groups) >= 6:
            break
    return groups


def _past_rows(db: Session, query: str, exclude_conversation_id: str | None, window: tuple[datetime, datetime] | None,
               scan: int = RECALL_SCAN) -> list[tuple[Message, Conversation]]:
    """Messages candidats : les plus récents, plus ceux de TOUTE date qui contiennent un mot de la question ou datent
    de la période évoquée. Sans ce second filet, une conversation de plus de 800 messages en arrière était oubliée.
    Un budget PAR MOT : un mot courant (« plafond ») ne noie jamais un mot rare (un nom, un quartier)."""
    q = db.query(Message, Conversation).join(Conversation, Conversation.id == Message.conversation_id) \
        .filter(Message.role.in_(("user", "assistant")))
    if exclude_conversation_id:
        q = q.filter(Message.conversation_id != exclude_conversation_id)
    rows = q.order_by(Message.created_at.desc()).limit(RECENT_SCAN).all()
    seen = {m.id for m, _ in rows}
    extra = []
    groups = _like_words(query)
    for g in groups:
        extra += q.filter(or_(*[Message.content.ilike(f"%{w}%") for w in g])) \
            .order_by(Message.created_at.desc()).limit(max(50, scan // len(groups))).all()
    if window:
        extra += q.filter(Message.created_at >= window[0], Message.created_at <= window[1]) \
            .order_by(Message.created_at.desc()).limit(400).all()
    for m, c in extra:
        if m.id not in seen:
            seen.add(m.id)
            rows.append((m, c))
    return rows


def recall_past(db: Session, query: str, exclude_conversation_id: str | None = None, budget: int = 2500,
                max_lines: int = 6, now: datetime | None = None) -> str:
    """Passages pertinents d'AUTRES conversations (mots communs + date évoquée), de toute date. Vide si rien de net."""
    now = now or _now()
    window = retrieval.evoked_window(query, now)
    rows = [(m, c.title) for m, c in _past_rows(db, query, exclude_conversation_id, window)]
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
        who = "Patron" if m.role == "user" else "UniC"
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


def search_conversations(db: Session, query: str, *, date_from: datetime | None = None, date_to: datetime | None = None,
                         limit: int = 5, per_conversation: int = 3, now: datetime | None = None) -> list[dict]:
    """Retrouve les conversations passées (archivées comprises, jamais effacées) qui parlent d'un sujet, avec leurs passages.

    Pour « on avait dit quoi pour le plafond de Mme Fall ? », « retrouve la conversation sur le devis Diop » : l'IA répond
    d'après ce qui a VRAIMENT été écrit, avec la date et le titre, au lieu de reconstruire de mémoire. Sans appel à l'IA."""
    now = now or _now()
    window = retrieval.evoked_window(query, now)
    if date_from or date_to:
        window = (date_from or datetime(2000, 1, 1, tzinfo=timezone.utc), date_to or now)
    noise = _SEARCH_NOISE | (_DATE_WORDS if window else frozenset())   # « la semaine dernière » : une période, pas un sujet
    words = [w for w in retrieval.tokens(query) if w not in noise and not (window and w.isdigit())]
    rows = _past_rows(db, query, None, window, SEARCH_SCAN)
    if window:
        rows = [(m, c) for m, c in rows if (d := _aware(m.created_at)) and window[0] <= d <= window[1]]
    if not rows:
        return []
    by_id = {m.id: (m, c) for m, c in rows}
    if words:
        ranked = retrieval.bm25(" ".join(words), [retrieval.Record(m.id, (m.content or "")[:1500], c.title or "") for m, c in rows])
        if not ranked:
            return []
        top = ranked[0][1]
        ranked = [(i, sc) for i, sc in ranked if sc >= 0.3 * top]
    else:   # seulement une période (« la semaine dernière ») : les échanges de cette période, du plus récent au plus ancien
        ranked = [(m.id, 1.0) for m, _ in sorted(rows, key=lambda r: _aware(r[0].created_at) or now, reverse=True)]
    groups: dict[str, dict] = {}
    for mid, _score in ranked:
        m, c = by_id[mid]
        g = groups.get(c.id)
        if g is None:
            if len(groups) >= limit:
                continue
            g = groups[c.id] = {"id": c.id, "titre": c.title or "", "archivee": bool(c.archived), "extraits": []}
        if len(g["extraits"]) < per_conversation:
            d = _aware(m.created_at)
            g["extraits"].append({"date": d.strftime("%d/%m/%Y") if d else "", "qui": "Patron" if m.role == "user" else "UniC",
                                  "texte": " ".join((m.content or "").split())[:320], "_at": d or now})
    out = []
    for g in groups.values():
        g["extraits"].sort(key=lambda e: e["_at"])
        for e in g["extraits"]:
            del e["_at"]
        g["date"] = g["extraits"][-1]["date"] if g["extraits"] else ""
        out.append(g)
    return out


def thread_recall(db: Session, conversation_id: str, query: str, exclude_ids: set[str], budget: int = 2500,
                  max_lines: int = 7) -> str:
    """Le fil de CETTE conversation au-delà des derniers échanges envoyés au modèle (exclude_ids).

    Sans lui, une longue conversation (un devis construit en 30 messages) oubliait son début : seuls les derniers messages
    partaient au modèle, et recall_past exclut volontairement la conversation en cours. On garde, sans appel à l'IA :
    1. la demande de départ du patron (le cadre du travail) ;
    2. les passages anciens qui parlent de la question actuelle (BM25) ;
    3. les trois derniers messages chiffrés du patron (dimensions, prix, quantités : les faits qu'il a posés).
    """
    rows = (db.query(Message).filter(Message.conversation_id == conversation_id, Message.role.in_(("user", "assistant")))
            .order_by(Message.created_at.asc()).all())
    older = [m for m in rows if m.id not in exclude_ids]
    if not older:
        return ""
    pos = {m.id: i + 1 for i, m in enumerate(rows)}
    picked: list[str] = []
    first = next((m for m in older if m.role == "user"), None)
    if first is not None:
        picked.append(first.id)
    ranked = retrieval.bm25(query, [retrieval.Record(m.id, (m.content or "")[:1500]) for m in older])
    if ranked:
        top = ranked[0][1]
        picked += [i for i, sc in ranked if sc >= 0.35 * top and i not in picked][:max_lines]
    figures = [m.id for m in older if m.role == "user" and re.search(r"\d", m.content or "")][-3:]
    picked += [i for i in figures if i not in picked]
    by_id = {m.id: m for m in older}
    lines, used = [], 0
    for mid in sorted(set(picked), key=lambda i: pos[i]):
        m = by_id[mid]
        who = "Patron" if m.role == "user" else "UniC"
        line = f"- [message {pos[mid]}] {who} : {' '.join((m.content or '').split())[:320]}"
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    return (f"PLUS TÔT DANS CETTE CONVERSATION ({len(older)} message(s) plus anciens que les derniers échanges ; "
            "le patron a pu corriger depuis : les messages récents priment) :\n" + "\n".join(lines))


# ---------- état mesuré ----------

def _device(path) -> int:
    return os.stat(path).st_dev


def state_report(db: Session) -> dict:
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
    "Une barre (fourrure, montant, rail, cornière) mesure 2,80 m. Une barre n'est pas un paquet : ne jamais confondre ni convertir l'un en l'autre.",
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
OWNER_RULES_V5 = (
    "Je n'utilise pas de « suspente » : un point d'accroche de faux plafond = 1 tige (300 FCFA l'unité) + 1 pivot + 1 cheville à laiton. "
    "Pivot = 6 500 FCFA le paquet de 100 ; chevilles à laiton = 6 000 FCFA le paquet de 100.",
)

OWNER_RULES_V6 = (
    "Ossature de faux plafond UniC : fourrures tous les 0,50 m (pas 0,60), une tige tous les 0,90 m sur chaque fourrure ; "
    "la plaque de 2 m se pose en travers des fourrures (plus résistant).",
)

OWNER_RULES_V7 = (
    "Moulures : barres de 3 m ; taille 4 = 3 500 FCFA la barre, taille 2 = 2 500 FCFA la barre ; nombre de barres = ⌈ longueur à couvrir / 3 ⌉. "
    "Colle silicone = 3 500 FCFA l'unité ; colle à pompe = 3 500 FCFA l'unité.",
    "Moulures, colles et peinture ne vont dans un devis BA13 QUE si je le demande.",
    "Peinture et finition : seau enduit 20 kg = 11 000 FCFA ; seau peinture Gylatex = 11 000 FCFA ; paquet papier ponçage = 8 000 FCFA ; "
    "toile = 5 000 FCFA le rouleau de 10 m².",
)

OWNER_RULES_V8 = (
    "Moulures : 1 colle pour 5 barres de moulure, arrondi au-dessus (⌈ barres / 5 ⌉). Colle silicone par défaut, colle à pompe si je la demande.",
)

OWNER_RULES_V9 = (
    "Devis : le tableau des matériaux ne contient QUE des fournitures. La livraison en fait partie et s'écrit « Livraison : à la charge du client » "
    "(0 FCFA, 1 forfait) sauf si je donne un prix. La main-d'œuvre n'est jamais mélangée aux matériaux : elle a son propre tableau séparé, en bas, "
    "avec la surface en m², le prix unitaire du m² puis le prix total (ligne dont la désignation commence par « Main-d'œuvre »).",
    "Un travail = un seul devis. Jamais deux devis à la fois ; une correction modifie le devis existant.",
)

OWNER_RULES_V10 = (
    "Cloison : chaque plaque (1,20 m de large) prend 3 montants, les deux bords et le milieu ; deux plaques voisines partagent "
    "le montant de jonction. Nombre de montants = ⌈ longueur / 1,20 ⌉ × 2 + 1 (5 m → 11 montants). L'autre face réutilise les "
    "mêmes montants. Toujours laisser l'outil de calcul compter, jamais de tête.",
)

OWNER_RULES_V11 = (
    "Cloison : chaque porte prend 3 montants de renfort en plus des montants de la cloison. L'outil de calcul les ajoute "
    "dès qu'une porte est citée.",
)

OWNER_RULES_V12 = (
    "Au Sénégal, toutes les barres d'ossature (fourrure, cornière, montant, rail) mesurent 2,80 m. Une barre n'est pas "
    "un paquet : ne jamais confondre ni convertir l'un en l'autre.",
)

OWNER_RULES_V13 = (
    "Tiges de faux plafond : la première à 30 cm du mur, puis une tous les 90 cm ; toujours une tige près de l'autre mur.",
    "Plaques de 1,20 × 2 m posées entières d'un mur jusqu'à l'autre : seule la dernière est coupée "
    "(6,47 m = 3 plaques de 2 m + un morceau de 47 cm).",
    "Fourrures tous les 50 cm : la plaque se pose en travers des fourrures (50 × 4 = 2 m, chaque bout sur une fourrure). "
    "Fourrures tous les 60 cm : la plaque se pose dans le sens des fourrures (60 × 2 = 1,20 m).",
)

OWNER_RULES_V14 = (
    "Cloison : un montant tous les 60 cm (plaque debout, 60 × 2 = 1,20 m) ou tous les 50 cm si je le dis (plaque couchée, "
    "50 × 4 = 2 m), le premier et le dernier contre le mur. À chaque jonction de plaques, 2 montants côte à côte (un par plaque), "
    "en 50 comme en 60 cm. À chaque angle droit, 2 montants. Cloison de 6 m en 60 cm : 11 + 4 = 15 montants.",
)

_RULE_SETS = {"v1": OWNER_RULES_V1, "v2": OWNER_RULES_V2, "v3": OWNER_RULES_V3, "v4": OWNER_RULES_V4, "v5": OWNER_RULES_V5,
              "v6": OWNER_RULES_V6, "v7": OWNER_RULES_V7, "v8": OWNER_RULES_V8, "v9": OWNER_RULES_V9, "v10": OWNER_RULES_V10,
              "v11": OWNER_RULES_V11, "v12": OWNER_RULES_V12,
              "v13": OWNER_RULES_V13, "v14": OWNER_RULES_V14}


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
        if version == "v14":   # l'ancienne règle « jonction partagée » (V10) est archivée : 2 montants à chaque jonction
            for m in db.query(Memory).filter(Memory.state == "active", Memory.text.like("Cloison : chaque plaque (1,20 m de large) prend 3 montants%")):
                m.state = "archived"
        if version == "v12":   # barres de 2,80 m : l'ancienne règle « 2,90 m » est archivée (rien à remplacer sur une base neuve)
            old = db.query(Memory).filter(Memory.state == "active", Memory.text.like("%barre%2,90 m%")).all()
            for m in old:
                m.state = "archived"
            rules = rules if old else ()
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


def extract_in_background(user_text) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if isinstance(user_text, dict):   # analyse d'une correction du patron (leçon à retenir)
            from app import lessons
            lessons.learn(db, user_text)
        else:
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


MAX_IMPORT_JSON_MB = 200   # protège d'une « bombe » zip (archive minuscule, contenu géant)


def candidates_from_export(raw: bytes, filename: str = "") -> list[str]:
    """Phrases du patron qui ressemblent à une règle, une préférence ou une tâche. Jamais exécutées, jamais des faits."""
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
                if name is None:
                    raise UnknownImport("Archive sans conversations.json.")
                if z.getinfo(name).file_size > MAX_IMPORT_JSON_MB * 1024 * 1024:
                    raise UnknownImport("conversations.json trop volumineux une fois décompressé.")
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
