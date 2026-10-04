"""Retrouver le bon passage sans tout charger dans le prompt : BM25 local (aucun service externe).

Sert à la mémoire des conversations passées, à la base de connaissances et aux documents reçus.
Un résultat porte toujours sa SOURCE (fichier, page, date) : une réponse sans source ne vaut pas mieux qu'une
réponse de mémoire.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._/-]*")
STOP_WORDS = frozenset("""
a ai as au aux avec car ce ces dans de des du elle en es est et eu eux il je la le les leur lui ma mais me meme mes
moi mon ne ni nos notre nous on or ou par pas pour qu que qui sa se ses si son sur ta te tes toi ton tu un une vos
votre vous y c d j l m n s t ca cela ceci comme comment quel quelle quels quelles pourquoi quand peut peux doit dois
veux fait faire etre avoir donc alors aussi tres plus moins bien the and for with that this what how
""".split())


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def tokens(text: str) -> list[str]:
    return [w for w in TOKEN_RE.findall(normalize(text)) if len(w) >= 2 and w not in STOP_WORDS]


def useful_words(text: str) -> set[str]:
    return set(tokens(text))


@dataclass(frozen=True)
class Record:
    id: str
    text: str
    title: str = ""


def bm25(query: str, records: list[Record], k1: float = 1.5, b: float = 0.75) -> list[tuple[str, float]]:
    """Classement BM25 : [(id, score)] décroissant. Le titre compte double."""
    q = tokens(query)
    if not q or not records:
        return []
    docs = [tokens(r.title) * 2 + tokens(r.text) for r in records]
    freqs = [Counter(d) for d in docs]
    df: Counter[str] = Counter()
    for f in freqs:
        df.update(f.keys())
    avg = sum(len(d) for d in docs) / max(1, len(docs))
    n = len(records)
    qc = Counter(q)
    out = []
    for rec, doc, freq in zip(records, docs, freqs):
        score, length = 0.0, max(1, len(doc))
        for tok, qn in qc.items():
            tf = freq.get(tok, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (n - df[tok] + 0.5) / (df[tok] + 0.5))
            score += qn * idf * (tf * (k1 + 1.0) / (tf + k1 * (1.0 - b + b * length / max(1.0, avg))))
        if score > 0:
            out.append((rec.id, score))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


# --- « hier », « la semaine dernière », « il y a 3 jours » : la question évoque une date ---
_UNITS = {"jour": 1, "jours": 1, "semaine": 7, "semaines": 7, "mois": 30, "an": 365, "ans": 365}
_NUMBERS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10}
_AGO = re.compile(r"il y a\s+(\d+|" + "|".join(_NUMBERS) + r")\s+(" + "|".join(_UNITS) + r")\b")
_SHORTCUTS = {"avant-hier": (1, 3), "hier": (0, 2), "la semaine derniere": (5, 14), "le mois dernier": (25, 40), "l annee derniere": (330, 400)}


def evoked_window(question: str, now: datetime | None = None) -> tuple[datetime, datetime] | None:
    now = now or datetime.now(timezone.utc)
    t = normalize(question).replace("'", " ")
    for expr, (lo, hi) in _SHORTCUTS.items():
        if expr in t:
            return now - timedelta(days=hi), now - timedelta(days=lo)
    m = _AGO.search(t)
    if not m:
        return None
    qty = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1)]
    days = qty * _UNITS[m.group(2)]
    margin = max(3.0, days * 0.35)
    return now - timedelta(days=days + margin), now - timedelta(days=max(0.0, days - margin))
