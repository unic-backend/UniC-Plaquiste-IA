"""Devis rangés dans Google Drive → devis de l'appli (même numérotation, PDF, suivi, encaissement que ceux créés ici).

Connexion : identifiant client + secret client + jeton d'actualisation Google avec le droit « drive.readonly » (lecture seule).
Testés auprès de Google AVANT d'être gardés, puis chiffrés (secrets_box) ; jamais renvoyés par l'API ni journalisés.
Import : seuls les PDF de devis UniC (modèle de l'appli) sont lus ; chaque ligne est vérifiée (quantité × prix = montant) et la somme
doit retomber sur le total imprimé, sinon rien n'est créé. Les prix du PDF sont gardés tels quels : aucun prix n'est inventé ni changé.
"""
from __future__ import annotations

import io
import re

import httpx
from sqlalchemy.orm import Session

from app import secrets_box
from app.models import AppSetting, Quotation

TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES = "https://www.googleapis.com/drive/v3/files"
TIMEOUT = 30.0
MAX_PDF = 10 * 1024 * 1024
_KEYS = ("drive_client_id", "drive_client_secret", "drive_refresh_token")   # tous chiffrés
_IMPORTED = "drive_import:"   # AppSetting drive_import:<id du fichier> → id du devis créé (un fichier n'est importé qu'une fois)


class DriveError(ValueError):
    """Message lisible, sans secret."""


# ---------- connexion ----------
def _get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return (secrets_box.decrypt(row.value) or "") if row and row.value else ""


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


CLIENT_ID_END = ".apps.googleusercontent.com"
# réponse de Google → cause en clair (le patron sait quelle case corriger)
TOKEN_ERRORS = {
    "invalid_client": "Google ne reconnaît pas l'identifiant client ou le secret : recopie-les depuis Google Cloud › Clients › "
                      "ton client Application Web.",
    "unauthorized_client": "Ce refresh token a été créé avec un autre identifiant client : refais-le dans OAuth Playground avec "
                           "ton identifiant et ton secret (roue crantée › « Use your own OAuth credentials »).",
    "invalid_grant": "Le refresh token est refusé (expiré, révoqué ou mal copié) : refais-le dans OAuth Playground et copie-le en entier.",
}


def _token(client_id: str, client_secret: str, refresh_token: str) -> str:
    try:
        r = httpx.post(TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token,
                                        "grant_type": "refresh_token"}, timeout=TIMEOUT)
    except httpx.HTTPError:
        raise DriveError("Google ne répond pas. Réessaie dans un instant.") from None
    if r.status_code != 200:
        try:
            err = str(r.json().get("error") or "")
        except ValueError:
            err = ""
        raise DriveError(TOKEN_ERRORS.get(err, "Google a refusé ces identifiants. Recopie l'identifiant client, le secret et le "
                                                "refresh token, puis réessaie."))
    return r.json()["access_token"]


def _creds(db: Session) -> tuple[str, str, str]:
    vals = tuple(_get(db, k) for k in _KEYS)
    if not all(vals):
        raise DriveError("Google Drive n'est pas connecté : Devis › Importer du Drive.")
    return vals   # type: ignore[return-value]


def _api(db: Session, url: str, params: dict | None = None) -> httpx.Response:
    tok = _token(*_creds(db))
    try:
        r = httpx.get(url, params=params, headers={"Authorization": f"Bearer {tok}"}, timeout=TIMEOUT)
    except httpx.HTTPError:
        raise DriveError("Google Drive ne répond pas. Réessaie dans un instant.") from None
    if r.status_code == 404:
        raise DriveError("Fichier introuvable dans le Drive.")
    if r.status_code != 200:
        raise DriveError("Google Drive a refusé la lecture (droit « drive.readonly » manquant ?).")
    return r


def connect(db: Session, client_id: str, client_secret: str, refresh_token: str) -> dict:
    vals = [v.strip() for v in (client_id, client_secret, refresh_token)]
    if not all(vals):
        raise DriveError("Les trois champs sont requis.")
    if not vals[0].endswith(CLIENT_ID_END) or " " in vals[0]:
        raise DriveError(f"Identifiant client incorrect : il finit par « {CLIENT_ID_END} » "
                         "(Google Cloud › Clients › ton client Application Web).")
    tok = _token(*vals)
    try:   # le droit de lecture du Drive est vérifié avant de garder quoi que ce soit
        r = httpx.get(FILES, params={"pageSize": 1, "fields": "files(id)"}, headers={"Authorization": f"Bearer {tok}"}, timeout=TIMEOUT)
    except httpx.HTTPError:
        raise DriveError("Google Drive ne répond pas. Réessaie dans un instant.") from None
    if r.status_code != 200:
        raise DriveError("Le jeton est valide mais n'a pas le droit de lire le Drive : ajoute « drive.readonly ».")
    for key, val in zip(_KEYS, vals):
        _put(db, key, secrets_box.encrypt(val))
    db.flush()
    return status(db)


def disconnect(db: Session) -> dict:
    for key in _KEYS:
        row = db.get(AppSetting, key)
        if row:
            db.delete(row)
    db.flush()
    return status(db)


def status(db: Session) -> dict:
    last = db.get(AppSetting, _LAST_COPY)
    return {"connected": all(_get(db, k) for k in _KEYS), "derniere_copie": last.value if last else ""}


# ---------- copie automatique des devis de l'appli dans le Drive (droit « drive.file » : seulement les fichiers créés par l'appli) ----------
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_COPY = "drive_copy:"   # AppSetting drive_copy:<id du devis> → id du fichier dans le Drive (une correction remplace le même fichier)
_LAST_COPY = "drive_last_copy"


def _copy_name(q: Quotation) -> str:
    client = re.sub(r"[^\w-]+", "_", (q.client_label or (q.customer.name if q.customer else "") or "Client").strip()).strip("_")
    return f"Devis_{q.number}_{client or 'Client'}.pdf"


def push_pdf(creds: tuple[str, str, str], data: bytes, name: str, file_id: str = "") -> str:
    """Envoie le PDF dans le Drive (nouveau fichier, ou remplace le contenu du fichier déjà créé par l'appli). Renvoie l'id du fichier."""
    tok = _token(*creds)
    auth = {"Authorization": f"Bearer {tok}"}
    if file_id:
        r = httpx.patch(f"{UPLOAD}/{file_id}", params={"uploadType": "media"}, content=data,
                        headers={**auth, "Content-Type": "application/pdf"}, timeout=60)
        if r.status_code == 200:
            return file_id   # fichier supprimé du Drive entre-temps (404) : on en recrée un
    boundary = "unicdevis" + re.sub(r"\W", "", name)[:20]
    meta = ('{"name": %s, "mimeType": "application/pdf"}' % __import__("json").dumps(name)).encode()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
            f"\r\n--{boundary}\r\nContent-Type: application/pdf\r\n\r\n".encode() + data + f"\r\n--{boundary}--".encode())
    r = httpx.post(UPLOAD, params={"uploadType": "multipart", "fields": "id"}, content=body,
                   headers={**auth, "Content-Type": f"multipart/related; boundary={boundary}"}, timeout=60)
    if r.status_code != 200:
        raise DriveError("Copie dans le Drive refusée : régénère le jeton avec aussi la portée « drive.file ».")
    return r.json()["id"]


def copy_quote_pdf(db: Session, q: Quotation, path) -> None:
    """Après chaque PDF de devis : copie dans le Drive en arrière-plan. Ne bloque ni ne fait jamais échouer le devis."""
    import os
    import threading
    from pathlib import Path
    if os.environ.get("UNIC_NO_BACKGROUND") or not status(db)["connected"]:
        return   # tests : pas de fil de fond ; Drive non connecté : rien à faire
    try:
        creds, data = _creds(db), Path(path).read_bytes()
    except (DriveError, OSError):
        return
    row = db.get(AppSetting, _COPY + q.id)
    args = (creds, data, _copy_name(q), row.value if row else "", q.id, q.number)
    threading.Thread(target=_copy_job, args=args, name="drive-copy", daemon=True).start()


def _copy_job(creds, data, name, file_id, quote_id, number) -> None:
    from datetime import datetime, timezone
    from app.database import SessionLocal
    when = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
    try:
        fid, note = push_pdf(creds, data, name, file_id), f"{number} copié le {when}"
    except Exception as exc:   # noqa: BLE001 — un échec de copie ne touche jamais le devis ; il est affiché sur la page Drive
        fid, note = "", f"{number} non copié le {when} : {exc if isinstance(exc, DriveError) else 'Google Drive injoignable'}"
    with SessionLocal() as db:
        if fid:
            _put(db, _COPY + quote_id, fid)
        _put(db, _LAST_COPY, note[:300])
        db.commit()


# ---------- recherche et lecture ----------
def search(db: Session, query: str = "", limit: int = 10) -> list[dict]:
    """PDF de devis du Drive (les plus récents d'abord), filtrés par les mots donnés (nom du client, numéro…)."""
    q = ["mimeType = 'application/pdf'", "trashed = false", "name contains 'Devis'"]
    for word in re.findall(r"[\w-]{2,}", query or "")[:4]:
        q.append(f"name contains '{word.replace(chr(39), '')}'")
    r = _api(db, FILES, {"q": " and ".join(q), "orderBy": "modifiedTime desc", "pageSize": max(1, min(limit, 25)),
                         "fields": "files(id,name,modifiedTime,size)"})
    return [{"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime", ""), "size": int(f.get("size") or 0)}
            for f in r.json().get("files", [])]


def download(db: Session, file_id: str) -> tuple[str, bytes]:
    if not re.fullmatch(r"[\w-]{10,200}", file_id or ""):
        raise DriveError("Identifiant de fichier invalide.")
    meta = _api(db, f"{FILES}/{file_id}", {"fields": "name,mimeType,size"}).json()
    if meta.get("mimeType") != "application/pdf":
        raise DriveError("Ce fichier n'est pas un PDF.")
    if int(meta.get("size") or 0) > MAX_PDF:
        raise DriveError("PDF trop lourd (10 Mo maximum).")
    data = _api(db, f"{FILES}/{file_id}", {"alt": "media"}).content
    if len(data) > MAX_PDF or not data.startswith(b"%PDF"):
        raise DriveError("Ce fichier n'est pas un PDF lisible.")
    return meta.get("name", ""), data


# ---------- lecture d'un PDF de devis UniC ----------
_NUM = re.compile(r"^-?\d{1,3}(?:[\s  ]\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")


def _num(s: str) -> float | None:
    s = re.sub(r"\s*(FCFA|F CFA|CFA|€|XOF)\s*$", "", s.strip(), flags=re.I)
    if s in ("—", "–", "-"):   # montant nul : le PDF de l'appli écrit « — » (ex. « Livraison : à la charge du client »)
        return 0.0
    if not _NUM.match(s):
        return None
    return float(re.sub(r"[\s  ]", "", s).replace(",", "."))


def _rows(lines: list[str], with_unit: bool) -> list[dict]:
    """Lignes d'un tableau : « N », désignation (1 ligne ou plus), [unité], quantité, P.U., montant."""
    out, i, n = [], 0, 1
    while i < len(lines):
        if lines[i] != str(n):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j] != str(n + 1):
            j += 1
        cells = lines[i + 1:j]
        if len(cells) < (5 if with_unit else 4):
            raise DriveError(f"Ligne {n} illisible dans le PDF.")
        pu, total = _num(cells[-2]), _num(cells[-1])
        m = re.match(r"^(-?[\d\s  ,]+?)\s*([^\d\s].*)?$", cells[-3])   # « 10 » ou « 1 forfait »
        qty = _num(m.group(1)) if m else None
        unit = (m.group(2) or "").strip() if m else ""
        desc_cells = cells[:-4] if with_unit else cells[:-3]
        if with_unit:
            unit = cells[-4]
        if None in (pu, total, qty) or not desc_cells:
            raise DriveError(f"Ligne {n} illisible dans le PDF.")
        if abs(qty * pu - total) > 1:
            raise DriveError(f"Ligne {n} : quantité × prix ≠ montant dans le PDF. Rien n'est importé.")
        unit = {"unité": "u", "unite": "u"}.get(unit.lower(), unit.lower()) if unit else "u"   # libellé du PDF → unité de l'appli
        out.append({"name": " ".join(desc_cells), "unit": unit, "quantity": qty, "unit_price": pu, "total": total})
        n, i = n + 1, j
    return out


def _between(lines: list[str], start: re.Pattern, end: re.Pattern) -> list[str]:
    try:
        a = next(k for k, l in enumerate(lines) if start.search(l))
    except StopIteration:
        return []
    b = next((k for k in range(a + 1, len(lines)) if end.search(lines[k])), len(lines))
    body = lines[a + 1:b]
    head = next((k for k, l in enumerate(body) if l.startswith("Montant")), -1)   # en-tête du tableau
    return body[head + 1:]


def parse_quote_pdf(data: bytes) -> dict:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        raise DriveError("PDF illisible.") from None
    lines = [l.strip() for l in text.splitlines() if l.strip() and not re.search(r"·\s*page \d+$", l.strip())]
    if not any(l == "DEVIS" for l in lines) or not any(l.startswith("Tableau des matériaux") or l.startswith("Main-d'œuvre") for l in lines):
        raise DriveError("Ce PDF n'est pas un devis UniC (modèle de l'appli) : import refusé.")

    def after(label: str) -> str:
        k = next((k for k, l in enumerate(lines) if l == label), -1)
        return lines[k + 1] if 0 <= k < len(lines) - 1 else ""

    obj_start = next((k for k, l in enumerate(lines) if l == "OBJET"), -1)
    obj_end = next((k for k in range(obj_start + 1, len(lines)) if lines[k].startswith(("Tableau des", "Main-d'œuvre"))), obj_start + 1)
    lieu = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("Lieu du chantier")), "")
    mats = _rows(_between(lines, re.compile(r"^Tableau des matériaux"), re.compile(r"^Sous-total matériaux")), with_unit=True)
    labour = _rows(_between(lines, re.compile(r"^Main-d'œuvre \(pose\)$"), re.compile(r"^Sous-total main-d'œuvre")), with_unit=False)
    total = _num(after("MONTANT TOTAL") or "")
    vat_line = next((l for l in lines if re.match(r"^TVA\s+[\d,]+\s*%", l)), "")
    vat_rate = float(re.search(r"([\d,]+)\s*%", vat_line).group(1).replace(",", ".")) / 100 if vat_line else None
    ht = sum(r["total"] for r in mats + labour)
    if not (mats or labour) or total is None:
        raise DriveError("Lignes ou total introuvables dans le PDF : import refusé.")
    expected = round(ht * (1 + vat_rate), 0) if vat_rate else ht
    if abs(expected - total) > 2:
        raise DriveError(f"La somme des lignes ({ht:,.0f}) ne retombe pas sur le total imprimé ({total:,.0f}) : import refusé.".replace(",", " "))
    return {"number": after("N°"), "date": after("DATE"), "client": after("CLIENT"), "lieu": lieu,
            "objet": " ".join(lines[obj_start + 1:obj_end]) if obj_start >= 0 else "", "materials": mats, "labour": labour,
            "subtotal": ht, "vat_rate": vat_rate, "total": total}


# ---------- création du devis dans l'appli ----------
def import_quote(db: Session, user_id: str | None, file_id: str) -> dict:
    """Crée le devis dans l'appli (nouveau numéro, PDF à l'en-tête, signature et cachet du patron). Une seule fois par fichier."""
    from app import pdfs, services
    done = db.get(AppSetting, _IMPORTED + file_id)
    if done and (q := db.get(Quotation, done.value)) is not None:
        return {"already": True, **_summary(q)}
    name, data = download(db, file_id)
    p = parse_quote_pdf(data)
    lines = [{"name": r["name"], "quantity": r["quantity"], "unit": r["unit"], "fixed_price": r["unit_price"], "status": "confirmed"}
             for r in p["materials"]]
    for r in p["labour"]:   # la main-d'œuvre reste dans son propre tableau : libellé reconnu comme main-d'œuvre
        label = r["name"] if pdfs._is_labour(r["name"]) else f"Main-d'œuvre — {r['name']}"
        lines.append({"name": label, "quantity": r["quantity"], "unit": r["unit"], "fixed_price": r["unit_price"], "status": "confirmed"})
    q = services.quotation_from_quantities(
        db, title="", quantities=lines, customer_id=None, project_id=None, user_id=user_id, client_name=p["client"] or "Client",
        objet=p["objet"], lieu=p["lieu"], vat_rate=p["vat_rate"],
        notes=f"Importé depuis Google Drive : {name} (n° d'origine {p['number'] or '—'}, du {p['date'] or '—'}).")
    if abs((q.total or 0) - p["total"]) > 2:   # garde-fou : le devis créé doit valoir exactement le PDF du Drive
        raise DriveError("Le devis recréé ne vaut pas le total du PDF : vérifie-le avant de l'utiliser.")
    _put(db, _IMPORTED + file_id, q.id)
    db.commit()
    return {"already": False, "origin_number": p["number"], **_summary(q)}


def _summary(q: Quotation) -> dict:
    return {"id": q.id, "numero": q.number, "client": q.client_label, "total": q.total, "complet": q.prices_complete}
