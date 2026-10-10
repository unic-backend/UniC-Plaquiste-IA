"""Suivi des encaissements : le « comptable de mes fichiers ».

Pour chaque client : devis valides, décision du client (en attente / accepté / refusé), sommes reçues, reste à encaisser,
pourcentages. Argent seulement : jamais l'avancement du chantier. Tous les calculs sont en code, aucun appel à l'IA.
Les e-mails ne font que SUGGÉRER (acceptation, paiement) : rien n'est appliqué sans le clic du patron."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import InboxMessage, Invoice, MailSeen, Payment, Quotation, QuoteAcceptance, Receipt, TrackingClient, utcnow
from app.services import _ACCENTS, _LINK_WORDS, audit, client_name_of, company_dict, generate_invoice_pdf, invoice_from_quote

DECISIONS = ("pending", "accepted", "declined")
KINDS = ("avance", "acompte", "solde", "autre")
MAX_AMOUNT = 10_000_000_000
NO_REPLY_DAYS = 7   # un devis sans réponse depuis autant de jours est signalé


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
    return [q for q in db.query(Quotation).options(selectinload(Quotation.customer)).order_by(Quotation.created_at).all()
            if q.status != "cancelled" and (q.total or 0) > 0]


def _received(db: Session, quote_id: str) -> float:
    return round(sum(r.amount or 0 for r in db.query(Receipt).filter(Receipt.quotation_id == quote_id).all()), 2)


def _received_all(db: Session) -> dict[str, float]:
    """Sommes reçues de tous les devis en UNE requête (le tableau de bord n'interroge plus la base devis par devis)."""
    return {qid: round(total or 0, 2) for qid, total in db.query(Receipt.quotation_id, func.sum(Receipt.amount)).group_by(Receipt.quotation_id).all()}


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


def _aware(d: datetime | None) -> datetime | None:
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def _quote_row(db: Session, q: Quotation, got: float | None = None) -> dict:
    total = q.total or 0
    got = _received(db, q.id) if got is None else got
    left = max(0.0, total - got)
    since = _aware(q.approved_at or q.created_at)
    waiting = (utcnow() - since).days if since and (q.client_decision or "pending") == "pending" else 0
    accepted_on = _aware(q.decided_at or q.approved_at or q.created_at)
    age = max(0, (utcnow() - accepted_on).days) if accepted_on and q.client_decision == "accepted" else 0
    return {"attente_jours": waiting, "accepte_jours": age, "collecte": q.collect_on.date().isoformat() if q.collect_on else None,
            **_quote_row_base(q, total, got, left)}


def _quote_row_base(q: Quotation, total: float, got: float, left: float) -> dict:
    return {"id": q.id, "numero": q.number, "titre": q.object_text[:120] if q.object_text else q.title, "lieu": q.site_location,
            "montant": round(total), "devise": q.currency or "FCFA", "decision": q.client_decision or "pending",
            "brouillon": q.status == "draft", "recu": round(got), "reste": round(left),
            "pct_recu": _pct(min(got, total), total), "pct_reste": _pct(left, total), "depasse": round(got - total) if got > total + 0.5 else 0,
            "date": q.created_at.date().isoformat() if q.created_at else None}


def _group(db: Session) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    received = _received_all(db)
    for q in valid_quotes(db):
        name = client_name_of(db, q) or "Client sans nom"
        g = groups.setdefault(client_key(name), {"key": client_key(name), "client": name, "quotes": []})
        g["quotes"].append(_quote_row(db, q, received.get(q.id, 0.0)))
    for row in db.query(TrackingClient).filter(TrackingClient.name != "").all():   # client créé avec « + », sans devis pour l'instant
        groups.setdefault(row.key, {"key": row.key, "client": row.name, "quotes": []})
    return groups


def _client_totals(g: dict) -> dict:
    acc = [r for r in g["quotes"] if r["decision"] == "accepted"]
    pend = [r for r in g["quotes"] if r["decision"] == "pending"]
    total = sum(r["montant"] for r in acc)
    got = sum(min(r["recu"], r["montant"]) for r in acc)
    left = sum(r["reste"] for r in acc)
    state = ("soldé" if acc and left <= 0 else "à encaisser" if acc else "en attente" if pend else "nouveau" if not g["quotes"] else "refusé")
    return {"key": g["key"], "client": g["client"], "accepte": total, "recu": got, "reste": left, "pct_recu": _pct(got, total),
            "pct_reste": _pct(left, total), "en_attente": sum(r["montant"] for r in pend), "nb_devis": len(g["quotes"]),
            "nb_attente": len(pend), "etat": state, "devise": g["quotes"][0]["devise"] if g["quotes"] else "FCFA"}


def _reminders(groups: dict[str, dict]) -> list[dict]:
    """Encaissements prévus (date choisie par le patron) sur des devis acceptés qui ont encore un reste : retards d'abord."""
    today = utcnow().date()
    out = []
    for g in groups.values():
        for r in g["quotes"]:
            if r["decision"] == "accepted" and r["reste"] > 0 and r["collecte"]:
                days = (today - datetime.fromisoformat(r["collecte"]).date()).days
                out.append({"key": g["key"], "client": g["client"], "numero": r["numero"], "reste": r["reste"], "devise": r["devise"],
                            "date": r["collecte"], "jours_retard": max(0, days), "dans_jours": max(0, -days)})
    out.sort(key=lambda x: x["date"])
    return out


def _chantiers(groups: dict[str, dict]) -> list[dict]:
    """Un chantier par devis accepté, créé tout seul. L'avancement = le pourcentage encaissé (argent seulement, pas de photos ni de suivi terrain)."""
    out = [{"key": g["key"], "client": g["client"], "id": r["id"], "numero": r["numero"], "titre": r["titre"], "lieu": r["lieu"],
            "montant": r["montant"], "recu": r["recu"], "reste": r["reste"], "avancement": r["pct_recu"], "devise": r["devise"],
            "termine": r["reste"] <= 0, "date": r["date"]}
           for g in groups.values() for r in g["quotes"] if r["decision"] == "accepted"]
    out.sort(key=lambda x: (x["termine"], -(x["date"] and int(x["date"].replace("-", "")) or 0)))
    return out


AGING = ((0, 30, "0 – 30 jours"), (31, 60, "31 – 60 jours"), (61, 90, "61 – 90 jours"), (91, None, "+ de 90 jours"))


def _aging(groups: dict[str, dict]) -> dict:
    """Balance âgée : le reste à encaisser rangé par ancienneté depuis l'acceptation du devis (le plus vieux argent dû se voit)."""
    rows = [(g, r) for g in groups.values() for r in g["quotes"] if r["decision"] == "accepted" and r["reste"] > 0]
    tranches = []
    for lo, hi, label in AGING:
        part = [r for _, r in rows if r["accepte_jours"] >= lo and (hi is None or r["accepte_jours"] <= hi)]
        tranches.append({"label": label, "reste": sum(r["reste"] for r in part), "nb": len(part)})
    total = sum(t["reste"] for t in tranches)
    for t in tranches:
        t["pct"] = _pct(t["reste"], total)
    oldest = max(rows, key=lambda gr: gr[1]["accepte_jours"], default=None)
    return {"tranches": tranches, "total": total,
            "plus_ancien": {"key": oldest[0]["key"], "client": oldest[0]["client"], "numero": oldest[1]["numero"],
                            "reste": oldest[1]["reste"], "jours": oldest[1]["accepte_jours"]} if oldest else None}


def _conversion(groups: dict[str, dict]) -> dict:
    """Taux d'acceptation des devis tranchés par le client (acceptés / acceptés + refusés). Les devis en attente ne comptent pas."""
    rows = [r for g in groups.values() for r in g["quotes"]]
    acc = sum(1 for r in rows if r["decision"] == "accepted")
    dec = sum(1 for r in rows if r["decision"] == "declined")
    return {"acceptes": acc, "refuses": dec, "taux": _pct(acc, acc + dec), "en_attente": sum(1 for r in rows if r["decision"] == "pending")}


def follow_up_message(client: str, numero: str, montant: float, devise: str, jours: int, company: str) -> str:
    """Relance polie d'un devis sans réponse : chiffres du suivi, sans IA. Le patron l'envoie lui-même."""
    amount = f"{round(montant):,}".replace(",", " ")
    return "\n".join([f"Bonjour {client},", "",
                      f"Je reviens vers vous au sujet du devis {numero} ({amount} {devise}) envoyé il y a {jours} jours.",
                      "Avez-vous pu l'étudier ? Je reste disponible pour toute question ou pour l'ajuster à votre besoin.", "",
                      "Cordialement,", company or "UniC Plaquiste"])


def _no_reply(groups: dict[str, dict], company: str = "") -> list[dict]:
    """Devis sans réponse du client depuis NO_REPLY_DAYS jours ou plus (brouillons exclus : pas encore envoyés)."""
    out = [{"key": g["key"], "client": g["client"], "numero": r["numero"], "montant": r["montant"], "devise": r["devise"],
            "jours": r["attente_jours"],
            "relance": follow_up_message(g["client"], r["numero"], r["montant"], r["devise"], r["attente_jours"], company)}
           for g in groups.values() for r in g["quotes"]
           if r["decision"] == "pending" and not r["brouillon"] and r["attente_jours"] >= NO_REPLY_DAYS]
    out.sort(key=lambda x: -x["jours"])
    return out


def removed(db: Session) -> list[dict]:
    """Devis retirés du suivi (récupérables)."""
    return [{"id": q.id, "numero": q.number, "client": client_name_of(db, q) or "Client sans nom", "montant": round(q.total or 0),
             "devise": q.currency or "FCFA"} for q in db.query(Quotation).filter(Quotation.status == "cancelled").order_by(Quotation.updated_at.desc()).limit(50).all()
            if (q.total or 0) > 0]


def overview(db: Session) -> dict:
    """Tableau de bord : chiffres globaux + une ligne par client (les plus gros restes à encaisser d'abord)."""
    sync_existing(db)
    groups = _group(db)
    clients = [_client_totals(g) for g in groups.values()]
    order = {"à encaisser": 0, "nouveau": 1, "en attente": 2, "soldé": 3, "refusé": 4}
    clients.sort(key=lambda c: (order[c["etat"]], -c["reste"], c["client"].lower()))
    accepted = sum(c["accepte"] for c in clients)
    got = sum(c["recu"] for c in clients)
    return {"accepte": accepted, "recu": got, "reste": sum(c["reste"] for c in clients), "pct_recu": _pct(got, accepted),
            "pct_reste": _pct(accepted - got, accepted) if accepted else 0.0,
            "en_attente": sum(c["en_attente"] for c in clients), "nb_attente": sum(c["nb_attente"] for c in clients),
            "nb_clients": len(clients), "nb_a_encaisser": sum(1 for c in clients if c["etat"] == "à encaisser"),
            "clients": clients, "devise": clients[0]["devise"] if clients else "FCFA",
            "rappels": _reminders(groups), "sans_reponse": _no_reply(groups, company_dict(db).get("name") or ""), "retires": removed(db), "chantiers": _chantiers(groups),
            "anciennete": _aging(groups), "conversion": _conversion(groups)}


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
    info = db.get(TrackingClient, key)
    phone = (info.phone if info else "") or next((q.customer.phone for q in valid_quotes(db) if client_key(client_name_of(db, q)) == key
                                                    and q.customer is not None and q.customer.phone), "") or ""
    gone = [{"id": q.id, "numero": q.number, "montant": round(q.total or 0)} for q in db.query(Quotation).filter(Quotation.status == "cancelled").all()
            if client_key(client_name_of(db, q)) == key and (q.total or 0) > 0]
    tot = _client_totals(g)
    site = (info.site if info else "") or next((r["lieu"] for r in g["quotes"] if r["lieu"]), "")
    return {**tot, "telephone": phone, "note": info.note if info else "", "lieu": site, "retires": gone, "documents": _documents(db, key),
            "message_point": point_message(db, g, tot),
            "devis": g["quotes"],
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


# ---------- fiche client : téléphone, note, rappels, retrait d'un devis ----------

def point_message(db: Session, g: dict, tot: dict) -> str:
    """Message « où en est votre dossier » : uniquement les chiffres du suivi, sans IA. Vide s'il n'y a rien à encaisser."""
    acc = [r for r in g["quotes"] if r["decision"] == "accepted" and r["reste"] > 0]
    if not acc:
        return ""
    money = lambda n: f"{n:,.0f}".replace(",", " ")   # noqa: E731
    lines = [f"Bonjour {g['client']},", "", "Voici le point sur votre dossier :"]
    for r in acc:
        lines.append(f"- Devis {r['numero']} : {money(r['montant'])} {r['devise']} · reçu {money(r['recu'])} ({str(r['pct_recu']).replace('.', ',')} %) · reste {money(r['reste'])}")
    lines += ["", f"Reste à régler : {money(tot['reste'])} {tot['devise']}.", "Merci de me confirmer la date de règlement.", "",
              "Cordialement,", company_dict(db).get("name") or "UniC Plaquiste"]
    return "\n".join(lines)


def set_client_info(db: Session, key: str, phone: str, note: str) -> dict:
    if key not in _group(db):
        raise TrackingError("Client introuvable dans le suivi.")
    row = db.get(TrackingClient, key)
    if row is None:
        row = TrackingClient(key=key)
        db.add(row)
    row.phone = re.sub(r"[^\d+ ().-]", "", phone or "")[:40]
    row.note = (note or "").strip()[:2000]
    row.updated_at = utcnow()
    db.commit()
    return {"telephone": row.phone, "note": row.note}


def set_collect_date(db: Session, quote: Quotation, day: str | None, user_id: str | None) -> dict:
    """Date du prochain encaissement prévu (vide = pas de rappel). Sert au rappel de l'appli."""
    if day:
        try:
            quote.collect_on = datetime.strptime(day, "%Y-%m-%d").replace(hour=9, tzinfo=timezone.utc)
        except ValueError:
            raise TrackingError("Date invalide.")
    else:
        quote.collect_on = None
    audit(db, user_id, "tracking_collect_date", "quotation", quote.id, f"{quote.number} {day or '-'}")
    db.commit()
    return _quote_row(db, quote)


def remove_quote(db: Session, quote: Quotation, user_id: str | None) -> dict:
    """Retire un devis du suivi (statut « annulé », récupérable). Refusé s'il y a de l'argent enregistré : on ne cache pas un encaissement."""
    if _received(db, quote.id) > 0:
        raise TrackingError(f"Le devis {quote.number} a des versements : annule-les d'abord.")
    if db.query(Invoice).filter(Invoice.quotation_id == quote.id, Invoice.status.notin_(("draft", "cancelled"))).first() is not None:
        raise TrackingError(f"Le devis {quote.number} a une facture approuvée : il ne peut pas être retiré.")
    quote.status = "cancelled"
    quote.collect_on = None
    audit(db, user_id, "tracking_remove_quote", "quotation", quote.id, quote.number)
    db.commit()
    return {"id": quote.id, "numero": quote.number}


def restore_quote(db: Session, quote: Quotation, user_id: str | None) -> dict:
    if quote.status != "cancelled":
        raise TrackingError("Ce devis n'est pas retiré.")
    quote.status = "approved" if quote.approved_at else "draft"
    audit(db, user_id, "tracking_restore_quote", "quotation", quote.id, quote.number)
    db.commit()
    return _quote_row(db, quote)


def _documents(db: Session, key: str) -> list[dict]:
    """Factures, bons de commande et de livraison du client (les devis sont listés à part)."""
    from app.models import DeliveryNote, PurchaseOrder
    out = []
    for kind, label, model in (("invoice", "Facture", Invoice), ("po", "Bon de commande", PurchaseOrder), ("dn", "Bon de livraison", DeliveryNote)):
        for r in db.query(model).order_by(model.created_at.desc()).all():
            if r.status != "cancelled" and client_key(client_name_of(db, r)) == key:
                out.append({"kind": kind, "label": label, "id": r.id, "numero": r.number, "statut": r.status,
                            "total": round(r.total) if getattr(r, "total", None) is not None else None})
    return out


def create_client(db: Session, name: str, phone: str = "", site: str = "", note: str = "") -> dict:
    """Nouveau client saisi à la main : sa fiche existe tout de suite, le dossier (devis, factures…) se prépare ensuite dans son chat."""
    name = " ".join((name or "").split())
    if not 2 <= len(name) <= 120:
        raise TrackingError("Donne le nom du client (2 caractères au moins).")
    key = client_key(name)
    existed = key in _group(db)
    if not existed:
        db.add(TrackingClient(key=key, name=name, site=(site or "").strip()[:255], note=(note or "").strip()[:2000],
                              phone=re.sub(r"[^\d+ ().-]", "", phone or "")[:40]))
        db.commit()
    return {"key": key, "existait": existed}


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


def update_receipt(db: Session, receipt_id: str, user_id: str | None, amount: float | None = None, kind: str | None = None,
                   method: str | None = None, note: str | None = None, received_at: datetime | None = None) -> dict:
    """Corrige un versement mal saisi (montant, type, date, moyen, note). Le paiement miroir et la facture suivent : le compteur est recalculé."""
    rc = db.get(Receipt, receipt_id)
    if rc is None:
        raise TrackingError("Versement introuvable.")
    quote = db.get(Quotation, rc.quotation_id)
    old = rc.amount
    if amount is not None:
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            raise TrackingError("Montant invalide.")
        if not 0 < amount <= MAX_AMOUNT:
            raise TrackingError("Le montant doit être supérieur à zéro.")
        rc.amount = amount
    if kind is not None:
        rc.kind = kind if kind in KINDS else "autre"
    if method is not None:
        rc.method = method[:64]
    if note is not None:
        rc.note = note[:500]
    if received_at is not None:
        rc.received_at = received_at if received_at.tzinfo else received_at.replace(tzinfo=timezone.utc)
    pay = db.get(Payment, rc.payment_id) if rc.payment_id else None
    if pay is not None:
        pay.amount, pay.method, pay.notes, pay.paid_at = rc.amount, rc.method, rc.note, rc.received_at
        inv = db.get(Invoice, pay.invoice_id)
        if inv is not None and inv.total is not None:
            inv.paid = max(0.0, round((inv.paid or 0) - old + rc.amount, 2))
            inv.remaining = max(0.0, round(inv.total - inv.paid, 2))
            if inv.status != "draft":
                inv.status = "paid" if inv.remaining <= 0 else ("partial" if inv.paid > 0 else "approved")
            else:
                generate_invoice_pdf(db, inv, user_id)
    audit(db, user_id, "tracking_receipt_edit", "quotation", rc.quotation_id, f"{old} -> {rc.amount}")
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


def build_statement(db: Session, key: str) -> Path:
    """RELEVÉ DE COMPTE d'un client : chaque devis accepté (convenu), chaque versement reçu, le reste à payer. Chiffres du suivi, sans IA."""
    from app.pdfs import build_document_pdf, fr_num
    data = client_file(db, key)
    acc = [r for r in data["devis"] if r["decision"] == "accepted"]
    if not acc:
        raise TrackingError("Aucun devis accepté pour ce client : rien à mettre sur un relevé.")
    company = company_dict(db)
    cur = data["devise"] or company.get("currency") or "FCFA"
    money = lambda n, _c=cur: f"{round(n or 0):,} {_c}".replace(",", " ")   # noqa: E731  montants entiers, comme le suivi
    by_quote: dict[str, list[dict]] = {}
    for v in data["versements"]:
        by_quote.setdefault(v["devis"], []).append(v)
    day = lambda iso: datetime.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""   # noqa: E731
    rows: list[list[str]] = []
    for r in sorted(acc, key=lambda x: x["date"] or ""):
        rows.append([day(r["date"]), f"<b>Devis {r['numero']}</b>" + (f" — {r['titre']}" if r["titre"] else ""), money(r["montant"], cur), "", ""])
        for v in sorted(by_quote.get(r["numero"], []), key=lambda x: x["date"] or ""):
            how = " — ".join(x for x in (v["type"], v["moyen"]) if x)
            rows.append([day(v["date"]), f"Versement reçu ({how})" if how else "Versement reçu", "", money(v["montant"], cur), ""])
        rows.append(["", f"Reste — {fr_num(r['pct_recu'], 1)} % reçu", "", "", f"<b>{money(r['reste'], cur)}</b>"])
    totals = [("Total convenu", money(data["accepte"], cur)), ("Total versé", money(data["recu"], cur)), ("RESTE À PAYER", money(data["reste"], cur))]
    customer = next((q.customer for q in valid_quotes(db) if q.id in {r["id"] for r in acc} and q.customer is not None), None)
    from app.services import party_text_customer, party_text_from_company
    client_txt = party_text_customer(customer) if customer is not None else data["client"]
    if customer is None and data["telephone"]:
        client_txt += f"\nTél. {data['telephone']}"
    stamp = utcnow().strftime("%Y%m%d")
    filename = f"UniC_Releve_{re.sub(r'[^A-Za-z0-9]+', '_', key)[:40] or 'client'}_{stamp}.pdf"
    dest = settings.artifacts_path / "statements" / filename
    build_document_pdf(
        dest, company=company, doc_label="RELEVÉ DE COMPTE", number=stamp, title=f"Relevé de compte — {data['client']}", status="",
        meta_lines=[f"Édité le {utcnow().strftime('%d/%m/%Y')}"] + ([f"Chantier : {data['lieu']}"] if data["lieu"] else []),
        party_left=("Émetteur", party_text_from_company(company)), party_right=("Client", client_txt),
        headers=["Date", "Opération", "Convenu", "Versé", "Reste"], rows=rows, col_widths=[58, 182, 84, 84, 84],
        totals=totals, notes="Relevé établi à partir des versements enregistrés. Merci de nous signaler tout écart.", warnings=[],
    )
    return dest
