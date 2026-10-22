"""Actions affirmées sans être faites : la pire hallucination d'un assistant qui agit.

« J'ai créé le devis », « c'est noté dans l'agenda », « j'ai préparé le brouillon » : le patron croit la chose faite.
Ce module lit la réponse et la compare aux outils qui ont RÉUSSI pendant ce tour (côté serveur, pas d'après le modèle).
Une affirmation à la première personne sur un objet dont aucun outil n'a réussi = affirmation fantôme. Pur : sans base ni IA.
"""
from __future__ import annotations

import re

# objet de l'affirmation → outils qui peuvent l'avoir réellement fait
FAMILIES: dict[str, tuple[re.Pattern, frozenset[str]]] = {
    "le devis": (re.compile(r"\bdevis\b", re.I), frozenset({"create_quote", "revise_document"})),
    "la facture": (re.compile(r"\bfactur", re.I), frozenset({"create_invoice", "create_balance_invoice", "revise_document"})),
    "le bon de commande": (re.compile(r"\bbons? de commande\b", re.I), frozenset({"create_purchase_order", "revise_document"})),
    "le bon de livraison": (re.compile(r"\bbons? de livraison\b", re.I), frozenset({"create_delivery_note", "revise_document"})),
    "l'e-mail": (re.compile(r"\be-?mails?\b|\bcourriels?\b|\bmails?\b|\bbrouillon de r[ée]ponse\b", re.I),
                 frozenset({"save_email_draft", "save_email_reply_draft"})),
    "le rendez-vous": (re.compile(r"\brendez-vous\b|\brdv\b|\bagenda\b", re.I), frozenset({"add_appointment", "update_appointment"})),
    "le versement": (re.compile(r"\bversement\b|\bpaiement\b|\bacompte\b|\bavance\b", re.I), frozenset({"record_receipt"})),
    "la publication": (re.compile(r"\bpublication\b|\bpost\b|\bannonce\b", re.I), frozenset({"save_social_post_draft"})),
    "le fichier": (re.compile(r"\bpdf\b|\bexcel\b|\bxlsx\b|\btableur\b|\bfichier\b", re.I),
                   frozenset({"make_pdf", "make_spreadsheet", "edit_file", "pdf_tool", "create_quote", "create_invoice",
                              "create_purchase_order", "create_delivery_note", "revise_document"})),
    "la mémoire": (re.compile(r"\bm[ée]moire\b|\bm[ée]moris|\bretenu\b|\bje m'en souviendrai\b", re.I), frozenset({"remember"})),
}

# « j'ai créé… », « je l'ai enregistré », « je viens d'ajouter… », « c'est fait : … » (première personne : l'action serait faite)
_PARTICIPLE = (r"cr[ée]{2}e?s?|g[ée]n[ée]r[ée]e?s?|pr[ée]par[ée]e?s?|r[ée]dig[ée]e?s?|enregistr[ée]e?s?|not[ée]e?s?|ajout[ée]e?s?|"
               r"modifi[ée]e?s?|corrig[ée]e?s?|m[ée]moris[ée]e?s?|retenue?s?|envoy[ée]e?s?|jointe?s?|programm[ée]e?s?|fix[ée]e?s?")
_INFINITIVE = r"cr[ée]er|g[ée]n[ée]rer|enregistrer|noter|ajouter|pr[ée]parer|r[ée]diger|envoyer|retenir|joindre|programmer"
_CLAIM = re.compile(
    rf"\b(?:j[’']ai|je l[’']ai|je les ai)\b(?:\s+\w+){{0,3}}?\s+({_PARTICIPLE})\b"
    rf"|\bje viens d[’'e]\s*({_INFINITIVE})\b"
    rf"|\bc[’']est (fait|not[ée]|enregistr[ée]|programm[ée])\b", re.I)
_SENT = re.compile(r"\benvoy|\benvoyer\b", re.I)
_STOP = re.compile(r"[;?]|\bveux|\bsouhait|\bsi\b|\bpour\b|\bque\b|\bmais\b|\bavant\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def unbacked(reply: str, succeeded: list[str] | set[str]) -> list[str]:
    """Objets que la réponse dit avoir faits sans qu'aucun outil correspondant ait réussi dans ce tour (vide = rien à redire).
    « envoyé » est toujours fantôme : l'assistant n'envoie jamais rien lui-même, c'est le patron qui envoie."""
    done = set(succeeded or ())
    found: list[str] = []
    for sentence in _sentences(reply):
        for m in _CLAIM.finditer(sentence):
            verb = m.group(1) or m.group(2) or m.group(3) or ""
            if _SENT.search(verb):
                found.append("l'envoi (l'assistant n'envoie jamais rien lui-même)")
                continue
            after = sentence[m.end():m.end() + 80]
            stop = _STOP.search(after)
            obj = sentence[max(0, m.start() - 50):m.start()] + " " + (after[:stop.start()] if stop else after)
            for label, (pattern, tools) in FAMILIES.items():
                if pattern.search(obj) and not (tools & done):
                    found.append(label)
    return list(dict.fromkeys(found))


def correction_prompt(items: list[str]) -> str:
    return ("[Contrôle automatique du serveur] Ta réponse affirme avoir fait : " + ", ".join(items) + ". "
            "Or aucun outil correspondant n'a réussi dans ce tour. Si le patron l'a demandé, fais-le maintenant avec l'outil "
            "adapté puis réponds ; sinon réécris ta réponse sans prétendre l'avoir fait (dis ce qui reste à faire). "
            "Si c'était fait dans un message précédent, dis-le clairement. Rien n'est jamais « envoyé » par toi : "
            "le patron approuve et envoie lui-même. Réponds directement au patron, sans parler de ce contrôle.")


def warning(items: list[str]) -> str:
    return ("\n\n⚠️ Vérification : cette réponse parle de " + ", ".join(items)
            + " comme si c'était fait, mais aucune action correspondante n'a été exécutée. Redemande-le si tu le veux.")
