"""Le briefing : ce que le patron doit savoir maintenant, assemblé à partir de ce qui est RÉELLEMENT branché.

Chaque rubrique dit son état : OK, NON_CONFIGURE, INDISPONIBLE. Une rubrique en panne n'empêche pas les autres, et
« rien à signaler » n'est jamais confondu avec « je n'ai pas pu regarder ».
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import connectors, google_business as gbp, mailbox, memory as mem, trust
from app.models import EmailDraft, InboxMessage, Invoice, Memory, Quotation, SocialPost

logger = logging.getLogger("unic.briefing")
OK, NOT_CONFIGURED, UNAVAILABLE = "OK", "NON_CONFIGURE", "INDISPONIBLE"
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")


@dataclass
class Section:
    title: str
    state: str
    text: str


def day_label(d: datetime) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def _quotes(db: Session) -> Section:
    rows = db.query(Quotation).filter(Quotation.status.in_(("draft", "sent"))).order_by(Quotation.created_at.desc()).all()
    if not rows:
        return Section("Devis à valider", OK, "Aucun devis en attente.")
    lines = [f"- {q.number} — {q.client_label or (q.customer.name if q.customer else 'client non renseigné')} — "
             f"{'total incomplet' if q.total is None else f'{q.total:,.0f} {q.currency}'.replace(',', ' ')}" for q in rows[:6]]
    more = f"\n(+ {len(rows) - 6} autres)" if len(rows) > 6 else ""
    return Section("Devis à valider", OK, f"{len(rows)} devis en brouillon ou envoyé(s) :\n" + "\n".join(lines) + more)


def _invoices(db: Session) -> Section:
    from app import unpaid
    u = unpaid.unpaid(db)
    late, soon = u["en_retard"], u["a_venir"]
    if not late and not soon:
        return Section("Factures à encaisser", OK, "Aucune facture en attente de paiement.")
    lines = []
    if late:
        lines.append(f"⚠️ {len(late)} en retard, {unpaid.fmt(u['total_retard'])} :")
        lines += [f"- {r['numero']} — {r['client']} — {unpaid.fmt(r['reste'])} {r['devise']}, {r['jours_retard']} j de retard" for r in late[:6]]
    if soon:
        lines.append(f"À venir : {len(soon)}, {unpaid.fmt(u['total_a_venir'])} :")
        lines += [f"- {r['numero']} — {r['client']} — {unpaid.fmt(r['reste'])} {r['devise']}, échéance {r['echeance']}" for r in soon[:4]]
    if late:
        lines.append("Dis « relance les impayés » : je prépare les messages, tu les envoies.")
    return Section("Factures à encaisser", OK, "\n".join(lines))


def _mail(db: Session) -> Section:
    if not mailbox.imap_configured():
        return Section("Courrier", NOT_CONFIGURED, "Boîte mail non connectée (Paramètres → Courrier).")
    try:
        info = connectors.sync_inbox(db, 15)
    except connectors.ConnectorError as exc:
        return Section("Courrier", UNAVAILABLE, str(exc))
    rows = db.query(InboxMessage).order_by(InboxMessage.fetched_at.desc()).limit(15).all()
    todo = [m for m in rows if not m.reply_draft_id]
    if not todo:
        return Section("Courrier", OK, f"{info['new']} nouveau(x). Rien en attente de réponse.")
    lines = [f"- {m.from_addr} — {m.subject or '(sans objet)'}" + (" ⚠️ contenu suspect" if trust.inspect(m.body) else "") for m in todo[:5]]
    return Section("Courrier", OK, f"{info['new']} nouveau(x) ; {len(todo)} sans réponse préparée :\n" + "\n".join(lines))


def _reviews() -> Section:
    if not gbp.configured():
        return Section("Avis Google", NOT_CONFIGURED, "Fiche Google non connectée (Paramètres → Réseaux & Google).")
    try:
        reviews = gbp.list_reviews()
    except gbp.GoogleError as exc:
        return Section("Avis Google", UNAVAILABLE, str(exc))
    todo = [r for r in reviews if not r["replied"]]
    if not todo:
        return Section("Avis Google", OK, "Tous les avis ont une réponse.")
    return Section("Avis Google", OK, f"{len(todo)} avis sans réponse :\n" + "\n".join(
        f"- {'★' * r['stars']} {r['author']} : {(r['comment'] or '(sans commentaire)')[:80]}" for r in todo[:5]))


def _google_plan(db: Session) -> Section:
    from app import gbp_plan
    p = gbp_plan.plan(db)
    if p["due"]:
        since = "aucune publication encore" if p["days_since"] is None else f"dernière il y a {p['days_since']} jour(s)"
        return Section("Fiche Google", OK, f"Publication avec photo à faire aujourd'hui ({since}). Thème conseillé : {p['theme']['label']}.")
    return Section("Fiche Google", OK, f"Publication à jour : la prochaine est attendue le {p['next_due_at'][:10]}.")


def _drafts(db: Session) -> Section:
    posts = db.query(SocialPost).filter(SocialPost.status != "published").count()
    mails = db.query(EmailDraft).filter(EmailDraft.status.in_(("draft", "approved"))).count()
    if not posts and not mails:
        return Section("Brouillons à valider", OK, "Aucun brouillon en attente.")
    return Section("Brouillons à valider", OK, f"{posts} publication(s) et {mails} e-mail(s) en attente d'approbation ou de publication.")


def _tasks(db: Session) -> Section:
    rows = db.query(Memory).filter(Memory.kind == "task", Memory.state == "active").order_by(Memory.created_at.desc()).all()
    if not rows:
        return Section("À faire", OK, "Aucune tâche notée. Dis « rappelle-moi de… » pour en ajouter.")
    return Section("À faire", OK, "\n".join(f"- {t.text}" for t in rows[:8]))


def _memory(db: Session) -> Section | None:
    n = len(mem.conflicts(db))
    guess = db.query(Memory).filter(Memory.state == "active", Memory.nature == "inference").count()
    if not n and not guess:
        return None
    parts = []
    if n:
        parts.append(f"{n} information(s) se contredisent")
    if guess:
        parts.append(f"{guess} supposition(s) à confirmer")
    return Section("Mémoire", OK, " ; ".join(parts) + ". (Paramètres → Mémoire)")


def compose(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sections: list[Section] = []
    for fn in (lambda: _tasks(db), lambda: _quotes(db), lambda: _invoices(db), lambda: _mail(db), _reviews,
               lambda: _google_plan(db), lambda: _drafts(db), lambda: _memory(db)):
        try:
            s = fn()
        except Exception as exc:   # une rubrique en panne n'arrête pas les autres
            logger.warning("rubrique en échec : %s", exc)
            s = Section("Rubrique", UNAVAILABLE, f"En échec : {type(exc).__name__}")
        if s is not None:
            sections.append(s)
    text = [f"**Briefing du {day_label(now)}**"]
    state_label = {NOT_CONFIGURED: " _(non connecté)_", UNAVAILABLE: " _(indisponible)_"}
    for s in sections:
        text += ["", f"**{s.title}**{state_label.get(s.state, '')}", s.text]
    return {"day": now.date().isoformat(), "sections": [asdict(s) for s in sections], "text": "\n".join(text)}
