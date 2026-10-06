"""UniC vocal : repère « appelle X » et « envoie un SMS à X : … » dans ce que le patron dit.

Le serveur ne fait JAMAIS l'action : il rend seulement l'intention (action, nom, message). Le téléphone retrouve le contact
(les contacts ne quittent pas le téléphone), demande le « oui » à voix haute, puis seulement appelle ou envoie.
Deux voies : règles fixes (marchent sans IA, même si Claude est coupé) puis Claude pour les tournures libres.
"""
from __future__ import annotations

import json
import re

from app.ai import chat_complete, provider_chain

CALL_RE = re.compile(
    r"^(?:s'il (?:te|vous) pla[iî]t[, ]+)?(?:(?:je\s+(?:veux|voudrais|aimerais|dois)|il\s+faut\s+que\s+je|peux[- ]tu|pouvez[- ]vous|tu\s+peux)\s+)?"
    r"(?:appelle|appeler|appelles|t[ée]l[ée]phone[rz]?|(?:passe|passer|passes|fais|faire|fait|donne|lance|lancer)(?:-moi)?\s+(?:un|des|l')\s*appels?)"
    r"(?:\s+(?:[àa]|au|aux|pour|vers|chez))?(?:\s+(?:le\s+num[ée]ro\s+)?(?P<who>.+?))?\s*[.!?]*$", re.I)
NOT_A_CALL = re.compile(r"^(?:d['’ ]\s*offres?|d['’ ]\s*d[ée]marche|commercial|publicitaire)", re.I)   # « appel d'offres » n'est pas un coup de téléphone
SMS_RE = re.compile(
    r"^(?:s'il (?:te|vous) pla[iî]t[, ]+)?(?:envoie|envoi|envoyer|[ée]cris|[ée]crire|manda|mande|texte|dis|pr[ée]viens|previens)\s+"
    r"(?:(?:un|une|le)\s+)?(?:sms|message|texto|mail|mess)?\s*(?:[àa]|au|aux)?\s*(?P<rest>.+?)\s*[.!?]*$", re.I)
SPLIT_RE = re.compile(r"\s*(?:,|:)\s+|\s+(?:que|qu'|en disant|disant|pour dire|pour lui dire|comme quoi|:)\s*", re.I)
LEAD_RE = re.compile(r"^(?:madame|monsieur|mme|mr|m\.)\s+", re.I)
TRIGGERS = re.compile(r"appel|t[ée]l[ée]phon|message|sms|texto|envoie|[ée]cris|dis\s+[àa]|pr[ée]ven|texte\s+[àa]|contacte|rappelle", re.I)
MAX_MESSAGE = 600


def _digits(who: str) -> str:
    who = re.sub(r"^(?:le|au)\s+(?:num[ée]ro\s+)?", "", who.strip(), flags=re.I)
    d = re.sub(r"[\s.\-()]", "", who)
    return d if re.fullmatch(r"\+?\d{8,15}", d) else ""


def _clean_name(s: str) -> str:
    s = re.sub(r"[\s,]*s'il (?:te|vous) pla[iî]t\s*[.!?]*$", "", s.strip(), flags=re.I)
    return re.sub(r"\s+", " ", s.strip(" ,.;:!?")).strip()


def parse_rules(text: str) -> dict | None:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return None
    m = CALL_RE.match(t)
    if m:
        who = _clean_name(m.group("who") or "")
        if NOT_A_CALL.match(who) or len(who.split()) > 5:
            return None
        num = _digits(who)
        return {"action": "call", "name": "" if num else who, "number": num, "message": ""}
    m = SMS_RE.match(t)
    if m and TRIGGERS.search(t):
        rest = m.group("rest")
        parts = SPLIT_RE.split(rest, maxsplit=1)
        who = _clean_name(parts[0])
        msg = _clean_name(parts[1]) if len(parts) > 1 else ""
        if not who or len(who.split()) > 5:
            return None
        num = _digits(who)
        return {"action": "sms", "name": "" if num else who, "number": num, "message": msg[:MAX_MESSAGE]}
    return None


def _ask_claude(text: str) -> dict | None:
    system = (
        "Tu lis ce que dit un patron de plaquisterie à son assistant vocal (français approximatif, mots déformés par l'accent). "
        "Dis s'il demande d'APPELER quelqu'un (« passer un appel », « téléphoner ») ou d'ENVOYER un SMS/message à quelqu'un, même sans dire le nom. Réponds par un JSON seul, sans texte autour : "
        '{"action":"call"|"sms"|"chat","name":"nom de la personne tel que dit","message":"texte à envoyer, vide si non dit"}. '
        'Tout le reste (devis, factures, questions, discussion) = "chat". N\'invente ni nom ni message.')
    res = chat_complete([{"role": "system", "content": system}, {"role": "user", "content": text}], deep=False, max_tokens=300)
    if not (res.available and res.text):
        return None
    m = re.search(r"\{.*\}", res.text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if d.get("action") not in ("call", "sms"):
        return None
    name = _clean_name(str(d.get("name") or ""))   # sans nom : le téléphone demande « à qui ? »
    num = _digits(name)
    return {"action": d["action"], "name": "" if num else name, "number": num,
            "message": _clean_name(str(d.get("message") or ""))[:MAX_MESSAGE] if d["action"] == "sms" else ""}


def parse(text: str, hint: bool = False) -> dict:
    """{action: call|sms|chat, name, number, message}. Règles d'abord ; Claude si un mot-clé du téléphone apparaît, ou si le
    téléphone a déjà repéré (mots mal dits compris) que la phrase parle d'appeler ou d'écrire (hint)."""
    found = parse_rules(text)
    if found is None and (hint or TRIGGERS.search(text or "")) and provider_chain():
        found = _ask_claude(text)
    return found or {"action": "chat", "name": "", "number": "", "message": ""}


def polish(text: str) -> str:
    """Corrige l'orthographe et la grammaire d'un SMS dicté, sans changer le sens ni le ton, sans rien ajouter. Sans IA : tel quel."""
    raw = re.sub(r"\s+", " ", (text or "").strip())[:MAX_MESSAGE]
    if not raw or not provider_chain():
        return raw
    system = ("Tu corriges un SMS dicté à voix haute : orthographe, grammaire, ponctuation. Garde EXACTEMENT le sens, le ton et la "
              "personne qui parle (pas de reformulation, aucune information ajoutée, pas de salutation en plus). "
              "Réponds uniquement par le SMS corrigé, rien d'autre.")
    res = chat_complete([{"role": "system", "content": system}, {"role": "user", "content": raw}], deep=False, max_tokens=300)
    out = re.sub(r"\s+", " ", (res.text or "").strip().strip('"«»'))
    if not (res.available and out) or len(out) > max(40, len(raw) * 2.5):
        return raw
    return out[:MAX_MESSAGE]
