"""Actions affirmées sans être faites : la pire hallucination d'un assistant qui agit.

« J'ai créé le devis », « c'est noté dans l'agenda », « ta facture est prête », « c'est envoyé ! » : le patron croit la chose faite.
Ce module lit la réponse et la compare aux outils qui ont RÉUSSI pendant ce tour (côté serveur, pas d'après le modèle).
Une affirmation sur un objet dont aucun outil n'a réussi = affirmation fantôme. Pur : sans base ni IA (les numéros de documents
qui existent en base sont fournis par l'appelant).

Trois tournures sont lues : à la première personne (« j'ai créé », « je t'ai préparé », « je viens d'ajouter »), au passif ou en état
(« le devis a été créé », « ta facture est prête », « c'est envoyé ») et en titre court (« Rendez-vous noté pour jeudi 10 h »).
Certaines actions ne sont JAMAIS faites par l'assistant, quels que soient les outils : envoyer, publier, appeler, contacter, payer,
approuver ou signer un document (c'est le patron qui le fait).
"""
from __future__ import annotations

import re

_I = re.I
_WEEKDAY_TIME = r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|apr[èe]s-demain)\b[^.;!?\n]{0,24}?\b\d{1,2}\s?h\b"

# objet de l'affirmation → outils qui peuvent l'avoir réellement fait (vide : l'assistant n'a aucun outil pour le faire dans le chat)
FAMILIES: dict[str, tuple[re.Pattern, frozenset[str]]] = {
    "le devis": (re.compile(r"\bdevis\b", _I), frozenset({"create_quote", "revise_document"})),
    "la facture": (re.compile(r"\bfactur|\b(?:un|l[’'])\s?avoir\b|\bfacture d[’']avoir\b", _I),
                   frozenset({"create_invoice", "create_balance_invoice", "revise_document"})),
    "le bon de commande": (re.compile(r"\bbons? de commande\b", _I), frozenset({"create_purchase_order", "revise_document"})),
    "le bon de livraison": (re.compile(r"\bbons? de livraison\b", _I), frozenset({"create_delivery_note", "revise_document"})),
    "l'e-mail": (re.compile(r"\be-?mails?\b|\bcourriels?\b|\bmails?\b|\bbrouillon de r[ée]ponse\b", _I),
                 frozenset({"save_email_draft", "save_email_reply_draft"})),
    "le rendez-vous": (re.compile(r"\brendez-vous\b|\brdv\b|\bagenda\b|\bvisite\b|" + _WEEKDAY_TIME, _I),
                       frozenset({"add_appointment", "update_appointment"})),
    "le versement": (re.compile(r"\bversement\b|\bpaiement\b|\bacompte\b|\bavance\b|\bencaissement\b", _I), frozenset({"record_receipt"})),
    "la publication": (re.compile(r"\bpublication\b|\bpost\b|\bannonce\b|\bstory\b", _I), frozenset({"save_social_post_draft"})),
    "le fichier": (re.compile(r"\bpdf\b|\bexcel\b|\bxlsx\b|\btableur\b|\bfichier\b|\bdocument\b", _I),
                   frozenset({"make_pdf", "make_spreadsheet", "edit_file", "pdf_tool", "create_quote", "create_invoice",
                              "create_balance_invoice", "create_purchase_order", "create_delivery_note", "revise_document",
                              "visit_report"})),
    "la mémoire": (re.compile(r"\bm[ée]moire\b|\bm[ée]moris|\bretenu\b|\bje m'en souviendrai\b", _I), frozenset({"remember", "forget_memory"})),
    "la fiche contact": (re.compile(r"\bfiches? (?:client|fournisseur|contact)\b|\bnouveau (?:client|fournisseur)\b|\b(?:dans|[àa]) (?:tes|vos|ton|votre|les) "
                                    r"(?:contacts|r[ée]pertoire|carnet)\b|\bcomme (?:client|fournisseur)\b", _I), frozenset({"create_contact"})),
    "le rappel": (re.compile(r"\brappels?\b|\brelances?\b", _I),
                  frozenset({"set_collect_reminder", "add_appointment", "update_appointment", "list_unpaid"})),
    "le visuel": (re.compile(r"\bvisuels?\b|\bimages?\b|\baffiches?\b|\bflyers?\b|\bsch[ée]mas?\b|\bdiagrammes?\b", _I),
                  frozenset({"generate_visual", "draw_diagram", "audit_logo"})),
    # « Studio vidéo », « scénario de la vidéo » : le lieu et le plan, pas la vidéo elle-même (qui n'est jamais faite dans le chat)
    "la vidéo": (re.compile(r"(?<!studio )(?<!sc[ée]nario de la )(?<!sc[ée]nario )\b(?:vid[ée]os?|clip)\b", _I), frozenset()),
    "le scénario vidéo": (re.compile(r"\bsc[ée]narios?\b", _I), frozenset({"plan_video"})),
    "l'agent": (re.compile(r"\bagents?\b", _I), frozenset({"create_agent"})),
    "le site": (re.compile(r"\bsite (?:web|internet)\b|\bpage du site\b|\bton site\b", _I), frozenset()),
    "le compte rendu": (re.compile(r"\bcompte[- ]rendu\b|\brapport de visite\b", _I), frozenset({"visit_report", "make_pdf"})),
    "la réponse à l'avis": (re.compile(r"\bavis (?:google|client)\b|\br[ée]ponse [àa] l[’']avis\b", _I), frozenset({"save_google_review_reply_draft"})),
}
# chat public du site : la demande du visiteur n'est transmise que si save_lead a réussi (sinon le gérant ne la verra jamais)
VISITOR_FAMILIES: dict[str, tuple[re.Pattern, frozenset[str]]] = {
    "vos coordonnées": (re.compile(r"\bcoordonn[ée]es\b|\bvotre demande\b|\bvotre num[ée]ro\b|\bvos informations\b|\bvotre message\b|"
                                   r"\bau g[ée]rant\b|\b[àa] l[’'][ée]quipe\b", _I), frozenset({"save_lead"})),
}
_DOCS = ("le devis", "la facture", "le bon de commande", "le bon de livraison")
_SEND_TARGETS = _DOCS + ("l'e-mail", "le fichier", "la publication")

# participes : ce que l'assistant dit avoir fait
_CREATE = r"cr[ée]{2}e?s?|g[ée]n[ée]r[ée]e?s?|pr[ée]par[ée]e?s?|r[ée]dig[ée]e?s?|[ée]tablie?s?"
_RECORD = (r"enregistr[ée]e?s?|not[ée]e?s?|ajout[ée]e?s?|inscrite?s?|m[ée]moris[ée]e?s?|retenue?s?|programm[ée]e?s?|planifi[ée]e?s?|"
           r"fix[ée]e?s?|cal[ée]e?s?|bloqu[ée]e?s?|r[ée]serv[ée]e?s?|rang[ée]e?s?|class[ée]e?s?|archiv[ée]e?s?|sauvegard[ée]e?s?|"
           r"jointe?s?|confirm[ée]e?s?|pr[êe]te?s?")
_CHANGE = (r"modifi[ée]e?s?|corrig[ée]e?s?|mise?s?\s+[àa]\s+jour|actualis[ée]e?s?|supprim[ée]e?s?|retir[ée]e?s?|effac[ée]e?s?|"
           r"annul[ée]e?s?|lanc[ée]e?s?|d[ée]plac[ée]e?s?|report[ée]e?s?")
_APPROVE = r"valid[ée]e?s?|approuv[ée]e?s?|sign[ée]e?s?"
_ALWAYS = r"envoy[ée]e?s?|partie?s?|publi[ée]e?s?|post[ée]e?s?|appel[ée]e?s?|t[ée]l[ée]phon[ée]e?s?|contact[ée]e?s?|pay[ée]e?s?"
_SEND = r"transmise?s?|partag[ée]e?s?|relanc[ée]e?s?"
_VERBS = "|".join((_CREATE, _RECORD, _CHANGE, _APPROVE, _ALWAYS, _SEND))
_FIRST_ONLY = r"pris(?:e|es)?"     # « j'ai pris rendez-vous » ; jamais au passif (« pris en compte »)

_CLAIMS = (
    ("first", re.compile(rf"\b(?:j[’']ai|je l[’']ai|je les ai|je t[’']ai|je te l[’']ai|je vous ai|je vous l[’']ai|nous avons|on a)\b"
                         rf"((?:\s+[\w’'-]+){{0,3}}?)\s+({_VERBS}|{_FIRST_ONLY})\b", _I)),
    ("viens", re.compile(r"\bje viens d[’'e]\s*((?:vous |te |t[’'])?)(cr[ée]er|g[ée]n[ée]rer|enregistrer|noter|ajouter|pr[ée]parer|r[ée]diger|"
                         r"retenir|joindre|programmer|planifier|r[ée]server|confirmer|modifier|corriger|mettre [àa] jour|supprimer|"
                         r"retirer|annuler|lancer|valider|approuver|signer|envoyer|publier|poster|appeler|t[ée]l[ée]phoner|contacter|"
                         r"payer|transmettre|partager|relancer)\b", _I)),
    ("cest", re.compile(rf"\bc[’']est\s+()(?:bien\s+|d[ée]j[àa]\s+|maintenant\s+)?(fait|{_VERBS})\b", _I)),
    ("passive", re.compile(rf"\b(?:a|ont)\s+()(?:bien\s+|d[ée]j[àa]\s+)?[ée]t[ée]\s+(?:bien\s+)?({_VERBS})\b", _I)),
    ("state", re.compile(rf"\b(?:est|sont)\s+()(?:bien\s+|maintenant\s+|d[ée]sormais\s+|d[ée]j[àa]\s+)?(en ligne|{_VERBS})\b", _I)),
    ("title", re.compile(rf"^\W*((?:[\w’'-]+\s+){{1,3}}?)({_VERBS}|{_FIRST_ONLY})\b", _I)),   # « Rendez-vous pris », « Devis créé »
)

_STOP = re.compile(r"[;?]|\bveux|\bsouhait|\bsi\b|\bpour\b|\bque\b|\bmais\b|\bavant\b", _I)
_HYPOTHESIS = re.compile(r"\b(?:si|s[’']il|s[’']ils|quand|d[èe]s que|d[èe]s qu[’']|lorsque|une fois|apr[èe]s que|avant que|pour que|afin que)\b", _I)
_NEGATION = re.compile(r"\b(?:pas|jamais|rien|point)\b", _I)
_PAST = re.compile(r"\b(?:hier|avant-hier|tout [àa] l[’']heure|plus t[ôo]t|pr[ée]c[ée]dente?s?|plus haut|la semaine derni[èe]re|le mois dernier|"
                   r"l[’']an dernier|il y a \d+|auparavant|le \d{1,2}(?:er)? (?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|"
                   r"septembre|octobre|novembre|d[ée]cembre))\b", _I)
# le patron (ou un tiers) a fait la chose : l'assistant ne fait que la rapporter
_ATTRIBUTED = re.compile(r"\b(?:tu|vous|il|elle|ils|elles)\s+(?:m[’']as|m[’']avez|as|avez|a|ont)\b|\bselon (?:toi|vous|lui|elle)\b|"
                         r"\bd[’']apr[èe]s (?:toi|vous|lui|elle)\b|\bcomme tu\b|\bpar (?:toi|vous|le client|la cliente|ton client|le fournisseur)\b", _I)
_NOT_YET = re.compile(r"^\s*(?:[àa]\s+(?:[êe]tre\s+)?(?:cr[ée]{2}|cr[ée]er|g[ée]n[ée]r|pr[ée]par|[ée]tabli|lanc|fai)|pour\s+(?:la\s+)?suite\b)", _I)
_TECH = re.compile(r"^\s*(?:l[’']outil|la fonction|les outils|get_|list_|read_|search_|save_|create_|make_)", _I)
_SUBJECT = re.compile(r"(?<![\w-])(?:a|ont|as|avez|avons|est|sont|es|suis|sera|seront|[ée]t[ée]|je|j[’']|tu|il|elle|on|nous|vous|ils|elles)(?![\w-])", _I)   # « rendez-vous » n'est pas « vous »
_OPINION = re.compile(r"^\s*(?:mon|ton|notre|votre) (?:avis|point de vue|analyse|ressenti)", _I)

ALWAYS_LABELS = (
    (re.compile(r"^(?:envoy|parti)", _I), "l'envoi (l'assistant n'envoie jamais rien lui-même)"),
    (re.compile(r"^(?:publi|post)", _I), "la publication (seul le patron publie)"),
    (re.compile(r"^(?:appel|t[ée]l[ée]phon|contact|transm|partag|relanc)", _I), "le contact d'une personne (l'assistant n'appelle et n'écrit à personne)"),
    (re.compile(r"^pay", _I), "le paiement (l'assistant ne paie rien)"),
)
APPROVAL = "l'approbation (seul le patron approuve et signe)"


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


_INFINITIVES = (
    ("always", r"envoyer|publier|poster|appeler|t[ée]l[ée]phoner|contacter|payer"),
    ("send", r"transmettre|partager|relancer"),
    ("approve", r"valider|approuver|signer"),
    ("change", r"modifier|corriger|mettre [àa] jour|supprimer|retirer|annuler|lancer"),
    ("create", r"cr[ée]er|g[ée]n[ée]rer|pr[ée]parer|r[ée]diger"),
)


def _kind(verb: str) -> str:
    """Nature de l'action dite : toujours fantôme (envoyer…), transmission, approbation, modification, création ou enregistrement."""
    v = " ".join(verb.lower().split())
    for name, pattern in (("always", _ALWAYS), ("send", _SEND), ("approve", _APPROVE), ("change", _CHANGE), ("create", _CREATE)):
        if re.fullmatch(pattern, v, _I):
            return name
    for name, pattern in _INFINITIVES:
        if re.fullmatch(pattern, v, _I):
            return name
    return "record"


def _always_label(verb: str) -> str:
    return next((label for p, label in ALWAYS_LABELS if p.search(verb)), ALWAYS_LABELS[0][1])


def unbacked(reply: str, succeeded: list[str] | set[str], *, known: set[str] | None = None,
             extra: dict[str, tuple[re.Pattern, frozenset[str]]] | None = None) -> list[str]:
    """Objets que la réponse dit avoir faits sans qu'aucun outil correspondant ait réussi dans ce tour (vide = rien à redire).
    `known` : numéros de documents cités qui existent déjà en base (« le devis UC-… a été créé » = déjà fait, pas inventé).
    `extra` : objets propres au contexte (chat du site : la demande du visiteur, transmise seulement par save_lead).
    Envoyer, publier, appeler, contacter, payer, approuver un document : jamais l'assistant, quels que soient les outils."""
    done = set(succeeded or ())
    families = {**FAMILIES, **(extra or {})}
    found: list[str] = []
    for sentence in _sentences(reply):
        question = sentence.rstrip().endswith("?")
        past = bool(_PAST.search(sentence))
        attributed = bool(_ATTRIBUTED.search(sentence))
        cites_known = any(re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", sentence) for k in (known or ()) if k)   # numéro entier : « UC-…-F » n'est pas « UC-… »
        for form, pattern in _CLAIMS:
            for m in pattern.finditer(sentence):
                between, verb = m.group(1) or "", m.group(2)
                if _NEGATION.search(between) or _HYPOTHESIS.search(sentence[max(0, m.start() - 40):m.start()]):
                    continue
                if form in ("cest", "passive", "state", "title") and (question or attributed):
                    continue
                after = sentence[m.end():m.end() + 80]
                if re.match(r"pr[êe]te?s?$", verb, _I) and _NOT_YET.match(after):
                    continue                                    # « prête à être créée » : pas encore faite
                if form == "title" and (_SUBJECT.search(between) or not any(p.search(between) for p, _ in families.values())):
                    continue                                    # titre court sans objet connu, ou vraie phrase (« le client a validé ») : rien ici
                stop = _STOP.search(after)
                obj = sentence[max(0, m.start() - 60):m.start()] + " " + between + " " + (after[:stop.start()] if stop else after)
                when = sentence[m.end():m.end() + 60]          # « noté pour jeudi 10 h » : l'heure suit souvent « pour »
                hits = [label for label, (p, _) in families.items() if p.search(obj)
                        or (label == "le rendez-vous" and re.search(_WEEKDAY_TIME, when, _I))]
                extra_hits = [label for label in hits if label in (extra or {})]
                backed_by_extra = any(families[label][1] & done for label in extra_hits)
                kind = _kind(verb)
                if kind in ("always", "send"):
                    if backed_by_extra or (re.match(r"appel", verb, _I) and _TECH.match(after)) or _OPINION.match(after):
                        continue
                    if extra_hits:                              # chat du site : « votre demande est transmise » sans save_lead
                        found += extra_hits
                    elif kind == "always" or any(label in _SEND_TARGETS for label in hits) \
                            or re.search(r"\bclients?\b|\bfournisseurs?\b", obj, _I):
                        found.append(_always_label(verb))
                    continue
                if kind == "approve" and any(label in _DOCS for label in hits):
                    found.append(APPROVAL)
                    continue
                if past or (cites_known and kind in ("create", "record")):
                    continue                                    # fait avant ce tour : le dire n'est pas inventer
                found += [label for label in hits if not (families[label][1] & done)]
    return list(dict.fromkeys(found))


def correction_prompt(items: list[str]) -> str:
    return ("[Contrôle automatique du serveur] Ta réponse affirme avoir fait : " + ", ".join(items) + ". "
            "Or aucun outil correspondant n'a réussi dans ce tour. Si le patron l'a demandé, fais-le maintenant avec l'outil "
            "adapté puis réponds ; sinon réécris ta réponse sans prétendre l'avoir fait (dis ce qui reste à faire). "
            "Si c'était fait dans un message précédent, dis-le clairement (« hier », « plus haut », avec le numéro du document). "
            "Tu n'envoies, ne publies, n'appelles, ne contactes, ne paies, n'approuves et ne signes jamais rien : le patron le fait "
            "lui-même après avoir relu. Réponds directement au patron, sans parler de ce contrôle.")


def warning(items: list[str]) -> str:
    return ("\n\n⚠️ Vérification : cette réponse parle de " + ", ".join(items)
            + " comme si c'était fait, mais aucune action correspondante n'a été exécutée. Redemande-le si tu le veux.")


def visitor_note(items: list[str]) -> str:
    """Chat public : une phrase claire pour le visiteur (rien n'est réservé tant que le gérant n'a pas rappelé)."""
    if "vos coordonnées" in items:
        return ("\n\nPour que le gérant vous rappelle, laissez-moi votre nom et votre numéro de téléphone : "
                "votre demande ne lui est pas encore transmise.")
    return "\n\nPrécision : rien n'est encore réservé ni confirmé. Le gérant vous rappelle pour fixer la visite et le prix."
