"""UniC Code : le moteur Claude Code pour tout ce qu'il sait faire hors du code de l'appli — site, jeu, application, script, outil, document.

1. Le patron décrit le projet (ou une suite d'un projet déjà livré).
2. Le serveur lance .github/workflows/unic-code.yml (GitHub Actions) : Claude Code travaille dans un dossier VIDE, sans aucun accès au
   dépôt de l'appli, teste son travail, et livre le projet en artefact « projet » (ZIP, gardé 30 jours par GitHub).
3. Le serveur suit l'exécution ; à la fin il garde le résumé, la liste des fichiers et l'aperçu autonome (apercu.html).
4. Le patron télécharge le ZIP, ouvre l'aperçu (affiché isolé : aucune donnée de l'appli n'y est accessible) ou demande une suite.
Rien n'est publié ni envoyé ailleurs. Dépense plafonnée par tâche (--max-budget-usd). Même connexion GitHub que l'Atelier.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import repair, secrets_box
from app.models import CodeTask, new_id

logger = logging.getLogger("unic.code")

WORKFLOW = "unic-code.yml"
BUDGETS = ("2", "5", "10")
BUDGET_DEFAULT = "5"                    # plafond de dépense par tâche (l'écran n'a plus de réglage : une seule zone de saisie)
ASK_MAX = 20_000
REQUEST_MIN, REQUEST_MAX = 10, 8_000
MAX_WORKING = 2
POLL_EVERY = timedelta(seconds=30)      # l'écran se rafraîchit toutes les 8 s : GitHub n'est interrogé qu'une fois sur quatre
LOST_AFTER = timedelta(minutes=20)
MAX_RUN = timedelta(hours=2)
ZIP_MAX = 60_000_000                    # au-delà, le ZIP ne passe pas par le serveur
SCAN_MAX = 25_000_000                   # lecture de l'aperçu et de la liste des fichiers
PREVIEW_MAX = 2_000_000
FILES_MAX = 300
PREVIEW_TTL = 600                       # lien d'aperçu valable 10 minutes
STEP_HINTS = {
    "Clé Claude (secret ANTHROPIC_API_KEY)": "Clé Claude absente sur GitHub : github.com › dépôt UniC-Plaquiste-IA › Settings › Secrets and "
                                             "variables › Actions › New repository secret › nom ANTHROPIC_API_KEY.",
    "Claude Code travaille": "Claude Code n'a pas terminé (plafond de dépense atteint ou erreur).",
    "Projet précédent": "Le projet à continuer n'est plus disponible sur GitHub (gardé 30 jours).",
    "Livraison du projet": "Claude Code n'a livré aucun fichier.",
}
# L'aperçu est le code de Claude : affiché dans une origine opaque (sandbox sans allow-same-origin), sans réseau, sans accès à l'appli.
PREVIEW_CSP = ("sandbox allow-scripts allow-forms allow-modals allow-popups; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' "
               "blob: data:; style-src 'unsafe-inline' data:; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; "
               "frame-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'")
WORKING_NOTE = "Claude Code travaille sur GitHub (5 à 40 minutes) : il crée, teste et prépare la livraison."


# ---------- une seule zone de saisie : le serveur choisit entre « projet » (dossier vide) et « code de l'appli » (tout le dépôt) ----------

APP_RE = re.compile(r"\b(unic[ -]?(?:ai|ia)|mon (?:ia|appli|application)|l['’ ]appli(?:cation)?|le chat|l['’]atelier|le studio|banc d['’]essai|"
                    r"l['’]apk|backend|frontend|le d[ée]p[oô]t|le repo|le menu|l['’]onglet|l['’][ée]cran|le clavier|le serveur)\b", re.I)
FIX_RE = re.compile(r"\b(bug|corrig\w*|r[ée]par\w*|erreur|probl[èe]me|plante\w*|cass[ée]\w*|cache|disparu|ne (?:marche|fonctionne) (?:pas|plus)|"
                    r"n['’]?arrive pas)\b", re.I)
FORCE_RE = re.compile(r"^\s*/(ia|app|projet|project)\b[ \t]*", re.I)
ROUTE_PROMPT = ("Tu classes la demande d'un patron en un seul mot. Réponds APP si elle demande de corriger, modifier ou ajouter une fonction à "
                "l'application UniC AI elle-même (ses écrans, son chat, son Atelier, son Studio, ses outils, son serveur, son code). "
                "Réponds PROJET si elle demande de créer autre chose (site, jeu, script, document, outil indépendant). Un seul mot, rien d'autre.")


def looks_like_app(text: str) -> bool:
    return bool(APP_RE.search(text or ""))


def job_kind(text: str) -> str:
    """« fix » (problème signalé) ou « feature » (nouvelle fonction) pour une tâche sur le code de l'appli."""
    return "fix" if FIX_RE.search(text or "") else "feature"


def classify(request: str) -> str:
    """« app » ou « projet ». Une courte question à Claude (modèle rapide, quelques centaines de jetons) ; si Claude ne répond pas
    (crédit, clé, réseau) : repli sur les mots de la demande. Jamais d'erreur : au pire, « projet » (dossier vide, sans danger)."""
    try:
        from app.ai import PROVIDERS
        from app.config import settings
        res = PROVIDERS["claude"].complete([{"role": "system", "content": ROUTE_PROMPT}, {"role": "user", "content": request[:1500]}],
                                           model=settings.anthropic_fast_model, max_tokens=8)
        word = (getattr(res, "text", "") or "").strip().upper()
        if getattr(res, "available", False) and word.startswith(("APP", "PROJET")):
            return "app" if word.startswith("APP") else "projet"
    except Exception:   # jamais bloquant : le repli ci-dessous décide
        logger.warning("UniC Code : classement par Claude impossible, repli sur les mots de la demande")
    return "app" if looks_like_app(request) else "projet"


def route(request: str) -> tuple[str, str]:
    """(« app » | « projet », demande nettoyée). « /ia … » et « /projet … » forcent le choix."""
    text = (request or "").strip()
    m = FORCE_RE.match(text)
    if m:
        return ("app" if m.group(1).lower() in ("ia", "app") else "projet"), text[m.end():].strip()
    return classify(text), text


class CodeError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _ctx(db: Session) -> tuple[str, str, str]:
    try:
        return repair._ctx(db)
    except repair.RepairError as exc:
        raise CodeError(str(exc), exc.status)


def _gh(method: str, path: str, tok: str, **kw):
    try:
        return repair._gh(method, path, tok, **kw)
    except repair.RepairError as exc:
        raise CodeError(str(exc), exc.status)


def _ok(r, what: str) -> dict:
    try:
        return repair._ok(r, what)
    except repair.RepairError as exc:
        raise CodeError(str(exc), exc.status)


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def to_dict(t: CodeTask) -> dict:
    return {"type": "project", "id": t.id, "request": t.request, "status": t.status, "title": t.title, "summary": t.summary, "error": t.error,
            "files": json.loads(t.files or "[]"), "preview": bool(t.preview), "budget": t.budget, "parent_id": t.parent_id,
            "zip": bool(t.artifact_id), "created_at": t.created_at.isoformat() if t.created_at else None}


# ---------- lancement ----------

def start(db: Session, request: str, budget: str = BUDGET_DEFAULT, parent_id: str = "", conv_id: str = "") -> CodeTask:
    text = (request or "").strip()
    if len(text) < REQUEST_MIN:
        raise CodeError("Décris le projet (une phrase au moins).")
    if len(text) > REQUEST_MAX:
        raise CodeError(f"Demande trop longue ({len(text)} caractères, {REQUEST_MAX} au plus).")
    if budget not in BUDGETS:
        raise CodeError("Plafond inconnu : 2, 5 ou 10 $.")
    parent = None
    if parent_id:
        parent = db.get(CodeTask, parent_id)
        if parent is None or parent.status != "done" or not parent.run_id:
            raise CodeError("Projet à continuer introuvable ou pas encore livré.", 404)
    if db.query(CodeTask).filter(CodeTask.status == "working").count() >= MAX_WORKING:
        raise CodeError("Deux projets sont déjà en cours : attends qu'ils finissent.", 409)
    tok, repo, base = _ctx(db)
    from app.config import settings
    task = CodeTask(id=new_id(), request=text, budget=budget, parent_id=parent.id if parent else "", summary=WORKING_NOTE, conv_id=conv_id)
    ask = text if parent is None else (f"SUITE DU PROJET (les fichiers du projet livré sont dans le dossier courant).\n"
                                       f"Demande d'origine : {parent.request[:3000]}\n\nCE QUE LE PATRON VEUT MAINTENANT :\n{text}")
    r = _gh("POST", f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches", tok, json={"ref": base, "inputs": {
        "task_id": task.id, "request": ask[:ASK_MAX], "model": settings.anthropic_model, "budget": budget,
        "parent_run": str(parent.run_id) if parent else ""}})
    if r.status_code != 204:   # rien n'est enregistré : la tâche n'existe que si GitHub l'a acceptée
        if r.status_code in (404, 422):
            raise CodeError(f"UniC Code n'est pas encore installé sur GitHub (workflow {WORKFLOW} absent de la branche {base}).", 503)
        if r.status_code == 403:
            raise CodeError("Le jeton GitHub n'a pas la permission « Actions : Read and write » : github.com › Settings › Developer "
                            "settings › ton jeton › Permissions.", 403)
        _ok(r, "lancement de UniC Code")
        raise CodeError(f"GitHub a refusé le lancement ({r.status_code}).", 502)
    db.add(task)
    db.commit()
    return task


# ---------- suivi ----------

def _find_run(tok: str, repo: str, task: CodeTask) -> dict | None:
    runs = _ok(_gh("GET", f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs", tok, params={"event": "workflow_dispatch", "per_page": 30}),
               "suivi de UniC Code").get("workflow_runs", [])
    return next((r for r in runs if r.get("display_title") == f"UniC Code {task.id}"), None)


def _artifacts(tok: str, repo: str, run_id: int) -> dict[str, dict]:
    arts = _ok(_gh("GET", f"/repos/{repo}/actions/runs/{run_id}/artifacts", tok), "livraison").get("artifacts", [])
    return {a.get("name", ""): a for a in arts if not a.get("expired")}


def _zip(tok: str, repo: str, artifact_id: int, limit: int) -> bytes | None:
    r = _gh("GET", f"/repos/{repo}/actions/artifacts/{artifact_id}/zip", tok, follow_redirects=True)
    if r.status_code in (404, 410):
        return None
    if r.status_code >= 300:
        _ok(r, "téléchargement")
    return r.content if len(r.content) <= limit else b""


def _note(tok: str, repo: str, arts: dict[str, dict]) -> str:
    """Résumé écrit par Claude Code (artefact « resume »). Vide si illisible : ce n'est qu'un plus."""
    art = arts.get("resume")
    if not art:
        return ""
    try:
        data = _zip(tok, repo, art["id"], 2_000_000)
        with zipfile.ZipFile(io.BytesIO(data or b"")) as z:
            info = z.getinfo("summary.md")
            return z.read(info).decode("utf-8", "replace").strip()[:4000] if info.file_size <= 200_000 else ""
    except (CodeError, KeyError, ValueError, zipfile.BadZipFile):
        return ""


def _failed_step(tok: str, repo: str, run_id: int) -> str:
    try:
        jobs = _ok(_gh("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs", tok), "étapes").get("jobs", [])
    except CodeError:
        return ""
    return next((s.get("name", "") for j in jobs for s in (j.get("steps") or []) if s.get("conclusion") == "failure"), "")


def _scan(data: bytes) -> tuple[list[str], str]:
    """Fichiers livrés et aperçu autonome (apercu.html à la racine du projet)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [i.filename for i in z.infolist() if not i.is_dir()]
            preview = ""
            info = next((i for i in z.infolist() if i.filename == "apercu.html"), None)
            if info is not None and info.file_size <= PREVIEW_MAX:
                preview = z.read(info).decode("utf-8", "replace")
    except (zipfile.BadZipFile, ValueError):
        return [], ""
    return sorted(names)[:FILES_MAX], preview


def follow(db: Session, task: CodeTask) -> None:
    """Projet en cours : suit l'exécution sur GitHub ; à la fin, garde la livraison ou explique l'échec."""
    if task.status != "working":
        return
    now = datetime.now(timezone.utc)
    if now - (_aware(task.updated_at) or now - POLL_EVERY) < POLL_EVERY:
        return
    tok, repo, _ = _ctx(db)
    run = _find_run(tok, repo, task)
    age = now - (_aware(task.created_at) or now)
    task.updated_at = now
    if run is None or run.get("status") != "completed":
        if run is None and age > LOST_AFTER:
            task.status, task.error = "failed", "Claude Code n'a pas démarré sur GitHub. Relance la demande."
        elif age > MAX_RUN:
            if run is not None:
                _gh("POST", f"/repos/{repo}/actions/runs/{run.get('id')}/cancel", tok)
            task.status, task.error = "failed", "Claude Code a dépassé 2 heures : projet arrêté."
        db.commit()
        return
    run_id = int(run.get("id") or 0)
    url = run.get("html_url", "")
    arts = _artifacts(tok, repo, run_id)
    note = _note(tok, repo, arts)
    title, _, rest = note.partition("\n")
    task.title = title.strip()[:120]
    task.summary = (rest.strip() or note)[:4000]
    if run.get("conclusion") != "success" or "projet" not in arts:
        step = _failed_step(tok, repo, run_id) if run.get("conclusion") != "success" else "Livraison du projet"
        why = STEP_HINTS.get(step) or (f"Étape « {step} » en échec." if step else f"Exécution {run.get('conclusion') or 'interrompue'}.")
        task.status, task.error = "failed", f"{why}\n\nDétail : {url}"[:1000]
        db.commit()
        return
    art = arts["projet"]
    task.run_id, task.artifact_id = run_id, int(art.get("id") or 0)
    files, preview = [], ""
    if int(art.get("size_in_bytes") or 0) <= SCAN_MAX:
        data = _zip(tok, repo, task.artifact_id, SCAN_MAX)
        if data:
            files, preview = _scan(data)
    task.files = json.dumps(files, ensure_ascii=False)
    task.preview = preview
    task.status = "done"
    db.commit()


def follow_all(db: Session) -> None:
    for task in db.query(CodeTask).filter(CodeTask.status == "working").all():
        try:
            follow(db, task)
        except CodeError:
            db.rollback()
            return   # GitHub injoignable ou non connecté : l'état reste tel quel
        except (KeyError, TypeError, ValueError):   # réponse GitHub inattendue pour UN projet : les autres restent suivis
            logger.warning("UniC Code : suivi impossible pour %s", task.id[:8])
            db.rollback()


# ---------- livraison : ZIP, aperçu, arrêt ----------

def download(db: Session, task: CodeTask) -> bytes:
    if task.status != "done" or not task.artifact_id:
        raise CodeError("Rien à télécharger.", 404)
    tok, repo, _ = _ctx(db)
    data = _zip(tok, repo, task.artifact_id, ZIP_MAX)
    if data is None:
        raise CodeError("Archive expirée sur GitHub (gardée 30 jours). Demande une suite pour régénérer le projet.", 410)
    if not data:
        raise CodeError("Projet trop lourd pour passer par l'appli (plus de 60 Mo).", 413)
    return data


def preview_token(task: CodeTask, now: float | None = None) -> str:
    return secrets_box.encrypt(f"{task.id}|{int((now or time.time()) + PREVIEW_TTL)}")


def preview_ok(task_id: str, token: str, now: float | None = None) -> bool:
    raw = secrets_box.decrypt(token or "") or ""
    tid, _, exp = raw.partition("|")
    return tid == task_id and exp.isdigit() and int(exp) >= (now or time.time())


def close(db: Session, task: CodeTask) -> None:
    """Arrête un projet en cours (l'exécution GitHub est annulée) ; rien d'autre n'est touché."""
    if task.status == "working":
        try:
            tok, repo, _ = _ctx(db)
            run = _find_run(tok, repo, task)
            if run is not None and run.get("status") != "completed":
                _gh("POST", f"/repos/{repo}/actions/runs/{run.get('id')}/cancel", tok)
        except CodeError:
            pass
        task.status, task.error = "closed", "Arrêté par le patron."
        db.commit()
