"""Suivi des encaissements : le « comptable de mes fichiers ».

Pour chaque client : devis valides, décision du client (en attente / accepté / refusé), sommes reçues, reste à encaisser,
pourcentages. Argent seulement : jamais l'avancement du chantier. Tous les calculs sont en code, aucun appel à l'IA.
Les e-mails ne font que SUGGÉRER (acceptation, paiement) : rien n'est appliqué sans le clic du patron."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import InboxMessage, Invoice, MailSeen, Payment, Quotation, QuoteAcceptance, Receipt, utcnow
from app.services import _ACCENTS, _LINK_WORDS, audit, client_name_of, generate_invoice_pdf, invoice_from_quote

DECISIONS = ("pending", "accepted", "declined")
KINDS = ("avance", "acompte", "solde", "autre")
MAX_AMOUNT = 10_000_000_000


class TrackingError(ValueError):
    """Message clair pour le patron (jamais une trace technique)."""


def _words(text: str) -> list[str]:
    clean = str(text or "").lower().translate(_ACCENTS)
    return [w for w in re.split(r"[^a-z0-9]+", clean) if w]


def client_key(name: str) -> str:
    """Même client quel que soit l'ordre des mots, la casse ou les accents."""
    return "-".join(sorted(w for w in _words(name) if w not in _LINK_WORDS)) or "sans-client"


def _pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def valid_quotes(db: Session) -> list[Quotation]:
    """Devis encore valables : ni annulés, ni sans montant. Un devis corrigé reste UN devis (même numéro, version suivante)."""
    return [q for q in db.query(Quotation).order_by(Quotation.created_at).all()
            if q.status != "cancelled" and (q.total or 0) > 0]


def _received(db: Session, quote_id: str) -> float:
    return round(sum(r.amount or 0 for r in db.query(Receipt).filter(Receipt.quotation_id == quote_id).all()), 2)


def sync_existing(db: Session) -> int:
    """Reprend ce qui existait déjà sans passer par le suivi : devis signés (= acceptés), paiements déjà posés sur une facture."""
    changed = 0
    for acc in db.query(QuoteAcceptance).all():
        q = db.get(Quotation, acc.quotation_id)
        if q is not None and q.client_decision == "pending":
            q.client_decision, q.decided_at = "accepted", acc.signed_at
            changed += 1
    mirrored = {r.payment_id for r in db.query(Receipt).filter(Receipt.payment_id.isnot(None)).all()}
    for pay in db.query(Payment).all():
        if pay.id in mirrored or (pay.amount or 0) <= 0:
            continue
        inv = db.get(Invoice, pay.invoice_id)
        q = db.get(Quotation, inv.quotation_id) if inv is not None and inv.quotation_id else None
        if q is None or inv.kind == "credit":
            continue
        db.add(Receipt(quotation_id=q.id, amount=pay.amount, kind="autre", received_at=pay.paid_at or utcnow(),
                       method=pay.method or "", note=f"Repris de la facture {inv.number}", payment_id=pay.id, created_by=pay.created_by))
        if q.client_decision == "pending":
            q.client_decision, q.decided_at = "accepted", pay.paid_at or utcnow()
        changed += 1
    if changed:
        db.commit()
    return changed


def _quote_row(db: Session, q: Quotation) -> dict:
    total = q.total or 0
    got = _received(db, q.id)
    left = max(0.0, total - got)
    return {"id": q.id, "numero": q.number, "titre": q.object_text[:120] if q.object_text else q.title, "lieu": q.site_location,
            "montant": round(total), "devise": q.currency or "FCFA", "decision": q.client_decision or "pending",
            "brouillon": q.status == "draft", "recu": round(got), "reste": round(left),
            "pct_recu": _pct(min(got, total), total), "pct_reste": _pct(left, total), "depasse": round(got - total) if got > total + 0.5 else 0,
            "date": q.created_at.date().isoformat() if q.created_at else None}


def _group(db: Session) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for q in valid_quotes(db):
        name = client_name_of(db, q) or "Client sans nom"
        g = groups.setdefault(client_key(name), {"key": client_key(name), "client": name, "quotes": []})
        g["quotes"].append(_quote_row(db, q))
    return groups


def _client_totals(g: dict) -> dict:
    acc = [r for r in g["quotes"] if r["decision"] == "accepted"]
    pend = [r for r in g["quotes"] if r["decision"] == "pending"]
    total = sum(r["montant"] for r in acc)
    got = sum(min(r["recu"], r["montant"]) for r in acc)
    left = sum(r["reste"] for r in acc)
    state = ("soldé" if acc and left <= 0 else "à encaisser" if acc else "en attente" if pend else "refusé")
    return {"key": g["key"], "client": g["client"], "accepte": total, "recu": got, "reste": left, "pct_recu": _pct(got, total),
            "pct_reste": _pct(left, total), "en_attente": sum(r["montant"] for r in pend), "nb_devis": len(g["quotes"]),
            "nb_attente": len(pend), "etat": state, "devise": g["quotes"][0]["devise"] if g["quotes"] else "FCFA"}


def overview(db: Session) -> dict:
    """Tableau de bord : chiffres globaux + une ligne par client (les plus gros restes à encaisser d'abord)."""
    sync_existing(db)
    clients = [_client_totals(g) for g in _group(db).values()]
    order = {"à encaisser": 0, "en attente": 1, "soldé": 2, "refusé": 3}
    clients.sort(key=lambda c: (order[c["etat"]], -c["reste"], c["client"].lower()))
    accepted = sum(c["accepte"] for c in clients)
    got = sum(c["recu"] for c in clients)
    return {"accepte": accepted, "recu": got, "reste": sum(c["reste"] for c in clients), "pct_recu": _pct(got, accepted),
            "pct_reste": _pct(accepted - got, accepted) if accepted else 0.0,
            "en_attente": sum(c["en_attente"] for c in clients), "nb_attente": sum(c["nb_attente"] for c in clients),
            "nb_clients": len(clients), "nb_a_encaisser": sum(1 for c in clients if c["etat"] == "à encaisser"),
            "clients": clients, "devise": clients[0]["devise"] if clients else "FCFA"}


def client_file(db: Session, key: str) -> dict:
    """Fiche d'un client : ses devis, ses sommes reçues, ses factures de solde."""
    sync_existing(db)
    g = _group(db).get(key)
    if g is None:
        raise TrackingError("Client introuvable dans le suivi.")
    ids = [r["id"] for r in g["quotes"]]
    receipts = db.query(Receipt).filter(Receipt.quotation_id.in_(ids)).order_by(Receipt.received_at.desc()).all()
    numbers = {r["id"]: r["numero"] for r in g["quotes"]}
    invs = db.query(Invoice).filter(Invoice.quotation_id.in_(ids), Invoice.kind == "final", Invoice.status != "cancelled").all()
    return {**_client_totals(g), "devis": g["quotes"],
            "versements": [{"id": r.id, "devis": numbers.get(r.quotation_id, ""), "montant": round(r.amount), "type": r.kind,
                            "date": r.received_at.date().isoformat() if r.received_at else None, "moyen": r.method, "note": r.note}
                           for r in receipts],
            "factures_solde": [{"id": i.id, "numero": i.number, "statut": i.status, "reste": round(i.remaining or 0)} for i in invs]}


def find_quote(db: Session, client: str = "", number: str = "", prefer: str = "open") -> Quotation:
    """Retrouve LE devis visé. Plusieurs candidats → TrackingError qui les liste : on demande au patron, on ne devine pas."""
    if number.strip():
        q = db.query(Quotation).filter(Quotation.number == number.strip().upper()).first()
        if q is None:
            raise TrackingError(f"Devis {number.strip().upper()} introuvable.")
        return q
    words = [w for w in _words(client) if w not in _LINK_WORDS]
    if not words:
        raise TrackingError("Précise le nom du client ou le numéro du devis.")
    found = [q for q in valid_quotes(db) if all(w in _words(client_name_of(db, q)) for w in words)]
    if not found:
        raise TrackingError(f"Aucun devis valide pour « {client.strip()} ».")
    rows = {q.id: _quote_row(db, q) for q in found}
    if prefer == "pending":
        pool = [q for q in found if rows[q.id]["decision"] == "pending"]
    else:
        pool = [q for q in found if rows[q.id]["decision"] != "declined" and rows[q.id]["reste"] > 0]
    pool = pool or found
    if len(pool) > 1 and prefer != "pending":   # de l'argent se pose sur le devis accepté, s'il n'y en a qu'un
        accepted = [q for q in pool if rows[q.id]["decision"] == "accepted"]
        pool = accepted if len(accepted) == 1 else pool
    if len(pool) > 1:
        raise TrackingError("Plusieurs devis pour ce client, lequel ? " + " ; ".join(
            f"{rows[q.id]['numero']} ({rows[q.id]['montant']:,} {rows[q.id]['devise']})".replace(",", " ") for q in pool))
    return pool[0]


def find_client(db: Session, name: str) -> str:
    """Clé du client dont le nom contient tous les mots donnés (ordre libre, sans accents)."""
    words = [w for w in _words(name) if w not in _LINK_WORDS]
    if not words:
        raise TrackingError("Précise le nom du client.")
    hits = [g for g in _group(db).values() if all(w in _words(g["client"]) for w in words)]
    if not hits:
        raise TrackingError(f"Aucun client « {name.strip()} » dans le suivi.")
    if len(hits) > 1:
        raise TrackingError("Plusieurs clients correspondent : " + " ; ".join(g["client"] for g in hits))
    return hits[0]["key"]


def set_decision(db: Session, quote: Quotation, decision: str, user_id: str | None) -> dict:
    if decision not in DECISIONS:
        raise TrackingError("Décision inconnue : accepté, refusé ou en attente.")
    quote.client_decision = decision
    quote.decided_at = None if decision == "pending" else utcnow()
    audit(db, user_id, "tracking_decision", "quotation", quote.id, f"{quote.number} {decision}")
    db.commit()
    return _quote_row(db, quote)


def _mirror(db: Session, quote: Quotation, rc: Receipt, user_id: str | None) -> None:
    """Si une facture existe déjà pour ce devis, le paiement y est aussi posé (le reliquat PDF et les impayés restent justes)."""
    inv = (db.query(Invoice).filter(Invoice.quotation_id == quote.id, Invoice.kind != "credit", Invoice.status != "cancelled")
           .order_by(Invoice.created_at.desc()).first())
    if inv is None or inv.total is None:
        return
    pay = Payment(invoice_id=inv.id, amount=rc.amount, paid_at=rc.received_at, method=rc.method, reference="suivi", notes=rc.note, created_by=user_id)
    db.add(pay)
    db.flush()
    rc.payment_id = pay.id
    inv.paid = round((inv.paid or 0) + rc.amount, 2)
    inv.remaining = max(0.0, round(inv.total - inv.paid, 2))
    if inv.status != "draft":
        inv.status = "paid" if inv.remaining <= 0 else "partial"
    else:
        generate_invoice_pdf(db, inv, user_id)   # un brouillon doit montrer le bon « payé / reste dû »


def record_receipt(db: Session, quote: Quotation, amount: float, kind: str = "avance", method: str = "", note: str = "",
                   user_id: str | None = None, received_at: datetime | None = None, mail_id: str | None = None) -> dict:
    """Enregistre une somme reçue. Recevoir de l'argent vaut acceptation du devis."""
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise TrackingError("Montant invalide.")
    if not 0 < amount <= MAX_AMOUNT:
        raise TrackingError("Le montant doit être supérieur à zéro.")
    if kind not in KINDS:
        kind = "autre"
    when = received_at or utcnow()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    rc = Receipt(quotation_id=quote.id, amount=amount, kind=kind, received_at=when, method=(method or "")[:64],
                 note=(note or "")[:500], mail_id=mail_id, created_by=user_id)
    db.add(rc)
    db.flush()
    if quote.client_decision != "accepted":
        quote.client_decision, quote.decided_at = "accepted", utcnow()
    _mirror(db, quote, rc, user_id)
    if mail_id:
        _seen(db, mail_id, "applied")
    audit(db, user_id, "tracking_receipt", "quotation", quote.id, f"{quote.number} +{amount}")
    db.commit()
    row = _quote_row(db, quote)
    if row["depasse"]:
        row["alerte"] = f"Attention : {row['depasse']} {row['devise']} de plus que le devis."
    return row


def cancel_receipt(db: Session, receipt_id: str, user_id: str | None) -> dict:
    """Annule une erreur de saisie : retire aussi le paiement miroir et rend à la facture ce qu'elle avait."""
    rc = db.get(Receipt, receipt_id)
    if rc is None:
        raise TrackingError("Versement introuvable.")
    quote = db.get(Quotation, rc.quotation_id)
    pay = db.get(Payment, rc.payment_id) if rc.payment_id else None
    if pay is not None:
        inv = db.get(Invoice, pay.invoice_id)
        if inv is not None:
            inv.paid = max(0.0, round((inv.paid or 0) - pay.amount, 2))
            inv.remaining = round((inv.total or 0) - inv.paid, 2) if inv.total is not None else inv.remaining
            if inv.status in ("paid", "partial"):
                inv.status = "partial" if inv.paid > 0 else "approved"
        db.delete(pay)
    db.delete(rc)
    audit(db, user_id, "tracking_receipt_cancel", "quotation", rc.quotation_id, f"{rc.amount}")
    db.commit()
    return _quote_row(db, quote)


def balance_invoice(db: Session, quote: Quotation, user_id: str | None) -> Invoice:
    """Facture de reliquat : lignes du devis, total du devis, déjà payé = ce que le client a versé, reste dû = ce qui manque.
    Créée en BROUILLON : le patron l'approuve et l'envoie lui-même."""
    got = _received(db, quote.id)
    if quote.client_decision != "accepted" and got <= 0:
        raise TrackingError(f"Le devis {quote.number} n'est pas marqué accepté.")
    if (quote.total or 0) - got <= 0:
        raise TrackingError(f"Le devis {quote.number} est déjà entièrement encaissé : pas de reliquat.")
    old = db.query(Invoice).filter(Invoice.quotation_id == quote.id, Invoice.kind == "final", Invoice.status != "cancelled").first()
    if old is not None:
        raise TrackingError(f"Facture de reliquat déjà créée : {old.number}.")
    inv = invoice_from_quote(db, quote, "final", user_id)
    left = round((quote.total or 0) - got, 2)
    inv.title = f"Facture de solde — {quote.object_text[:80] or quote.title}".strip(" —")
    inv.paid, inv.remaining = got, left
    inv.notes = f"Issue du devis {quote.number}. Déjà reçu : {got:,.0f}. Reste à payer : {left:,.0f}.".replace(",", " ")
    for rc in db.query(Receipt).filter(Receipt.quotation_id == quote.id, Receipt.payment_id.is_(None)).all():
        pay = Payment(invoice_id=inv.id, amount=rc.amount, paid_at=rc.received_at, method=rc.method, reference="suivi", notes=rc.note, created_by=user_id)
        db.add(pay)
        db.flush()
        rc.payment_id = pay.id
    generate_invoice_pdf(db, inv, user_id)
    audit(db, user_id, "tracking_balance_invoice", "invoice", inv.id, inv.number)
    db.commit()
    db.refresh(inv)
    return inv


# ---------- e-mails : suggestions seulement ----------

_ACCEPT_RE = re.compile(r"j'accepte|nous acceptons|accept[ée]|d'accord|bon pour accord|ok pour le devis|je valide|nous validons|"
                        r"valid[ée]|go pour|vous pouvez (?:commencer|d[ée]marrer)|on peut commencer", re.I)
_PAY_RE = re.compile(r"virement|vers[ée]|r[ée]gl[ée]|paiement|avance|acompte|wave|orange money|ch[eè]que|transf[ée]r[ée]", re.I)
_AMOUNT_RE = re.compile(r"(\d{1,3}(?:[ .  ]\d{3})+|\d{4,})\s*(?:fcfa|f\s?cfa|cfa|xof|f\b)", re.I)


def _seen(db: Session, mail_id: str, action: str) -> None:
    row = db.get(MailSeen, mail_id)
    if row is None:
        db.add(MailSeen(mail_id=mail_id, action=action))
    else:
        row.action = action


def dismiss_mail(db: Session, mail_id: str) -> None:
    _seen(db, mail_id, "dismissed")
    db.commit()


def _snippet(text: str, rx: re.Pattern) -> str:
    m = rx.search(text)
    if not m:
        return ""
    a = max(0, m.start() - 70)
    return " ".join(text[a:m.end() + 110].split())


def mail_hints(db: Session, limit: int = 20) -> list[dict]:
    """E-mails récents qui semblent dire « j'accepte » ou « j'ai payé » pour un client suivi. Contenu de tiers : extrait court, jamais exécuté."""
    done = {m.mail_id for m in db.query(MailSeen).all()} | {r.mail_id for r in db.query(Receipt).filter(Receipt.mail_id.isnot(None)).all()}
    groups = _group(db)
    names = {k: set(w for w in _words(g["client"]) if w not in _LINK_WORDS and len(w) > 1) for k, g in groups.items()}
    out: list[dict] = []
    for m in db.query(InboxMessage).order_by(InboxMessage.fetched_at.desc()).limit(80).all():
        if m.id in done:
            continue
        text = f"{m.subject}\n{m.body[:3000]}"
        hay = set(_words(f"{m.from_addr} {text}"))
        for key, ws in names.items():
            if not ws or not ws <= hay:
                continue
            g = groups[key]
            open_q = [r for r in g["quotes"] if r["decision"] != "declined"]
            pending = [r for r in g["quotes"] if r["decision"] == "pending"]
            money = _AMOUNT_RE.search(text)
            amount = int(re.sub(r"\D", "", money.group(1))) if money else None
            if _PAY_RE.search(text) and (amount or any(r["decision"] == "accepted" for r in g["quotes"])):
                kind, snip = "paiement", _snippet(text, _PAY_RE)
            elif pending and _ACCEPT_RE.search(text):
                kind, snip = "acceptation", _snippet(text, _ACCEPT_RE)
            else:
                continue
            target = (pending if kind == "acceptation" else [r for r in open_q if r["reste"] > 0] or open_q)
            out.append({"mail_id": m.id, "client": g["client"], "signal": kind, "de": m.from_addr[:120], "objet": m.subject[:140],
                        "date": m.date, "extrait": snip[:260], "montant": amount,
                        "devis": target[0]["numero"] if len(target) == 1 else None,
                        "devis_id": target[0]["id"] if len(target) == 1 else None,
                        "devis_possibles": [r["numero"] for r in target] if len(target) > 1 else []})
            break
        if len(out) >= limit:
            break
    return out
