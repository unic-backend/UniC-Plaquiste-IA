"""UniC se corrige et s'améliore lui-même — sans jamais toucher la production sans le clic du patron.

1. Un problème (incident) ou une demande de fonction arrive.
2. Claude Opus (raisonnement profond) lit le code ACTUEL dans le dépôt GitHub et écrit le correctif + un test.
3. Le serveur vérifie le correctif (chemins autorisés, remplacements exacts, Python qui compile) puis ouvre une
   PULL REQUEST sur une branche à part : la production ne change pas.
4. GitHub Actions lance tous les tests sur cette branche.
5. Le patron voit le résumé et l'état des tests ; « Fusionner » n'est possible que si les tests sont verts.
   Après fusion, Render redéploie (crochet de déploiement si fourni, sinon « Manual Deploy »).

Le jeton GitHub (accès au seul dépôt de l'appli) est chiffré (secrets_box), jamais renvoyé ni écrit dans un journal.
Zones protégées (sécurité, secrets, déploiement, ce mécanisme lui-même) : jamais modifiées par l'IA.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app import secrets_box
from app.models import AppSetting, Incident, RepairJob

logger = logging.getLogger("unic.repair")

DEFAULT_REPO = "unic-backend/UniC-Plaquiste-IA"
CODE_PREFIXES = ("backend/app/", "backend/tests/", "frontend/src/", "docs/")
CODE_EXT = (".py", ".ts", ".tsx", ".css", ".md", ".json")
PROTECTED = (
    "backend/app/auth.py", "backend/app/security.py", "backend/app/secrets_box.py", "backend/app/config.py",
    "backend/app/repair.py", "backend/app/selfcare.py", "backend/app/trust.py",
    ".github/", "Dockerfile", "render.yaml", "docker-compose.yml", ".env", "backend/requirements",
)
MAX_FILES_READ = 10
MAX_CHARS = 260_000
MAX_EDITS = 30
BRANCH_PREFIX = "unic-ai/"
REQUIRED_CHECKS = ("backend", "frontend")   # jobs de .github/workflows/tests.yml


RELEASE_RE = re.compile(r"\b(apk|d[ée]ploie\w*|red[ée]ploie\w*|mise? en ligne|render|nouveau lien|new lien)\b", re.I)
CODE_VERB_RE = re.compile(r"\b(ajoute\w*|corrige\w*|modifie\w*|change\w*|supprime\w*|retire\w*|affiche\w*|cr[ée]e\w*|bouton|page)\b", re.I)


def is_release_request(text: str) -> bool:
    """« Donne le nouvel APK », « redéploie sur Render » : une publication, pas du code à écrire."""
    t = (text or "").strip()
    return len(t) <= 160 and bool(RELEASE_RE.search(t)) and not CODE_VERB_RE.search(t)


class RepairError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ---------- réglages (jeton chiffré) ----------

def _get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else ""


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def _token(db: Session) -> str:
    raw = _get(db, "repair_gh_token")
    return (secrets_box.decrypt(raw) or "") if raw else ""


def _hook(db: Session) -> str:
    raw = _get(db, "repair_deploy_hook")
    return (secrets_box.decrypt(raw) or "") if raw else ""


def deployed_branch() -> str:
    """Branche que Render a déployée (variable fournie par Render) : les corrections se proposent sur CE code, pas sur main."""
    b = os.environ.get("RENDER_GIT_BRANCH", "").strip()
    return b if re.fullmatch(r"[\w./-]{1,120}", b) else ""


def status(db: Session) -> dict:
    return {"connected": bool(_token(db)), "repo": _get(db, "repair_repo") or DEFAULT_REPO,
            "base": deployed_branch() or _get(db, "repair_base") or "", "deploy_hook": bool(_hook(db))}


def connect(db: Session, token: str, repo: str = "", base: str = "", deploy_hook: str = "") -> dict:
    token = (token or "").strip()
    repo = (repo or DEFAULT_REPO).strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise RepairError("Dépôt invalide (format : propriétaire/nom).")
    if token:
        r = _gh("GET", f"/repos/{repo}", token)
        if r.status_code != 200:
            raise RepairError("Jeton refusé par GitHub ou dépôt inaccessible : vérifie l'accès « Contents » et « Pull requests ».", 400)
        perms = r.json().get("permissions") or {}
        if perms and not perms.get("push"):
            raise RepairError("Ce jeton ne peut pas écrire dans le dépôt : donne-lui « Contents : Read and write ».", 400)
        _put(db, "repair_gh_token", secrets_box.encrypt(token))
        if not base:
            base = r.json().get("default_branch") or "main"
    elif not _token(db):
        raise RepairError("Colle le jeton GitHub.")
    _put(db, "repair_repo", repo)
    if base:
        if not re.fullmatch(r"[\w./-]{1,120}", base):
            raise RepairError("Branche invalide.")
        _put(db, "repair_base", base.strip())
    if deploy_hook:
        if not deploy_hook.startswith("https://api.render.com/deploy/"):
            raise RepairError("Crochet de déploiement Render attendu (https://api.render.com/deploy/…).")
        _put(db, "repair_deploy_hook", secrets_box.encrypt(deploy_hook.strip()))
    db.commit()
    return status(db)


def disconnect(db: Session) -> None:
    for k in ("repair_gh_token", "repair_deploy_hook"):
        row = db.get(AppSetting, k)
        if row:
            db.delete(row)
    db.commit()


# ---------- GitHub ----------

def _gh(method: str, path: str, token: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=40) as c:
            return c.request(method, f"https://api.github.com{path}", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    except httpx.HTTPError:
        raise RepairError("GitHub injoignable depuis le serveur. Réessaie dans un instant.", 502)


def _ok(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 300:
        try:
            msg = (r.json().get("message") or "")[:160]
        except ValueError:
            msg = ""
        raise RepairError(f"GitHub a refusé ({what}) : {r.status_code} {msg}", 502)
    return r.json() if r.content else {}


def _ctx(db: Session) -> tuple[str, str, str]:
    tok = _token(db)
    if not tok:
        raise RepairError("Atelier non connecté à GitHub : Paramètres › Atelier › Connecter GitHub.", 400)
    st = status(db)
    base = st["base"] or _ok(_gh("GET", f"/repos/{st['repo']}", tok), "dépôt").get("default_branch", "main")
    return tok, st["repo"], base


def allowed(path: str) -> bool:
    p = (path or "").strip()
    if not p or p.startswith("/") or ".." in p.split("/") or "\\" in p:
        return False
    if any(p == x or p.startswith(x) for x in PROTECTED):
        return False
    return p.startswith(CODE_PREFIXES) and p.endswith(CODE_EXT)


def _tree(tok: str, repo: str, base: str) -> list[dict]:
    data = _ok(_gh("GET", f"/repos/{repo}/git/trees/{base}", tok, params={"recursive": "1"}), "liste des fichiers")
    return [{"path": t["path"], "size": t.get("size", 0)} for t in data.get("tree", [])
            if t.get("type") == "blob" and t["path"].startswith(CODE_PREFIXES) and t["path"].endswith(CODE_EXT)]


def _read(tok: str, repo: str, base: str, path: str) -> str:
    try:
        with httpx.Client(timeout=40) as c:
            r = c.get(f"https://api.github.com/repos/{repo}/contents/{path}", params={"ref": base}, headers={
                "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github.raw+json", "X-GitHub-Api-Version": "2022-11-28"})
    except httpx.HTTPError:
        raise RepairError("GitHub injoignable.", 502)
    if r.status_code == 404:
        return ""
    if r.status_code >= 300:
        raise RepairError(f"Lecture impossible : {path}", 502)
    return r.text


# ---------- Claude écrit le correctif ----------

PICK_TOOL = {
    "name": "pick_files",
    "description": "Choisis les fichiers à lire pour comprendre et corriger (10 maximum, les plus pertinents d'abord).",
    "input_schema": {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_FILES_READ}},
                     "required": ["paths"], "additionalProperties": False},
}
PATCH_TOOL = {
    "name": "submit_patch",
    "description": ("Rends le correctif. edits : remplacements EXACTS (search = extrait copié tel quel du fichier, unique dans ce "
                    "fichier, quelques lignes de contexte ; replace = nouveau texte). new_files : fichiers à créer. "
                    "Ajoute ou adapte un test dans backend/tests quand c'est du Python."),
    "input_schema": {"type": "object", "properties": {
        "title": {"type": "string", "description": "Titre court (français), ex. « Corrige le calcul des tiges »."},
        "summary": {"type": "string", "description": "Pour le patron, 2 à 5 lignes simples : cause, correction, risque."},
        "edits": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "search": {"type": "string"}, "replace": {"type": "string"}},
            "required": ["path", "search", "replace"], "additionalProperties": False}},
        "new_files": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}},
        "cannot": {"type": "string", "description": "Si tu ne peux pas corriger sûrement : pourquoi (alors edits vide)."},
    }, "required": ["title", "summary", "edits"], "additionalProperties": False},
}

RULES = (
    "Tu es l'ingénieur principal d'UniC AI (FastAPI + SQLAlchemy/SQLite côté serveur, React/Vite/TypeScript + Capacitor côté "
    "appli). Tu corriges ou améliores TON PROPRE CODE. Règles : changement minimal et sûr ; même style que le code autour "
    "(commentaires en français, sobres) ; aucune dépendance nouvelle ; ne supprime ni n'affaiblis jamais un test, une "
    "vérification de sécurité, l'approbation du patron avant envoi/publication, ni une règle métier du patron ; ne touche pas "
    "aux zones protégées (authentification, secrets, déploiement, atelier de réparation) ; aucun secret dans le code. "
    "Pour un bug : trouve la CAUSE racine, corrige-la et ajoute un test qui l'aurait détecté. Si ce n'est pas faisable "
    "sûrement avec les fichiers lus, remplis `cannot` au lieu d'inventer."
)


def _claude(system: str, user: str, tool: dict, deep: bool) -> dict:
    """Appelle Claude et récupère l'appel d'outil demandé."""
    from app.ai import ClaudeAIProvider
    from app.config import settings
    got: dict = {}

    def handler(name, args):
        if name == tool["name"]:
            got.update(args)
            return {"ok": True, "note": "Reçu. Termine en une ligne."}
        return {"error": "Outil inconnu."}

    res = ClaudeAIProvider().complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=settings.anthropic_model if deep else settings.anthropic_fast_model,
        tools=[tool], tool_handler=handler, max_tokens=16000 if deep else 2000, effort="high" if deep else None,
        thinking=deep)
    if not got:
        raise RepairError(f"Claude n'a pas rendu de proposition ({res.error or 'réponse sans correctif'}).", 502)
    return got


def apply_edits(files: dict[str, str], edits: list[dict], new_files: list[dict]) -> dict[str, str]:
    """Applique les remplacements exacts ; refuse tout ce qui est ambigu ou hors zone."""
    out: dict[str, str] = {}
    if len(edits) + len(new_files) > MAX_EDITS:
        raise RepairError("Correctif trop grand pour être sûr : découpe la demande.")
    for e in edits:
        p = e.get("path", "")
        if not allowed(p):
            raise RepairError(f"Fichier interdit ou protégé : {p}")
        cur = out.get(p, files.get(p))
        if cur is None:
            raise RepairError(f"Fichier non lu : {p}")
        n = cur.count(e.get("search", ""))
        if not e.get("search") or n != 1:
            raise RepairError(f"Remplacement {'introuvable' if n == 0 else 'ambigu'} dans {p}.")
        out[p] = cur.replace(e["search"], e.get("replace", ""), 1)
    for f in new_files:
        p = f.get("path", "")
        if not allowed(p) or p in files:
            raise RepairError(f"Création refusée : {p}")
        out[p] = f.get("content", "")
    for p, text in out.items():
        if p.endswith(".py"):
            try:
                compile(text, p, "exec")
            except SyntaxError as exc:
                raise RepairError(f"Le correctif casse la syntaxe de {p} (ligne {exc.lineno}) : refusé.")
    if not out:
        raise RepairError("Correctif vide.")
    return out


def _incident_text(db: Session, job: RepairJob) -> tuple[str, list[str]]:
    if not job.incident_id:
        return "", []
    i = db.get(Incident, job.incident_id)
    if i is None:
        return "", []
    paths = []
    for f in re.findall(r'File "([^"]+)"', i.detail or ""):
        m = re.search(r"(backend/app/[\w/]+\.py|app/[\w/]+\.py)$", f)
        if m:
            p = m.group(1) if m.group(1).startswith("backend/") else "backend/" + m.group(1)
            if p not in paths:
                paths.append(p)
    text = (f"PROBLÈME VU PAR LA SURVEILLANCE ({i.kind}, {i.count} fois) — source {i.source}\n{i.message}\n\n"
            f"TRACE :\n{(i.detail or '(aucune)')[-5000:]}")
    return text, paths


def run_job(db: Session, job: RepairJob) -> RepairJob:
    """Du problème à la pull request. Toute erreur laisse le job « failed » avec une explication."""
    try:
        tok, repo, base = _ctx(db)
        problem, trace_paths = _incident_text(db, job)
        ask = problem or f"DEMANDE DU PATRON ({'nouvelle fonction' if job.kind == 'feature' else 'problème signalé'}) :\n{job.request}"
        if problem and job.request:
            ask += f"\n\nPRÉCISION DU PATRON : {job.request}"
        tree = _tree(tok, repo, base)
        listing = "\n".join(f"{t['path']} ({t['size'] // 1024} ko)" for t in tree)
        picked = _claude(RULES, f"{ask}\n\nFICHIERS DU DÉPÔT :\n{listing}", PICK_TOOL, deep=False).get("paths", [])
        wanted = [p for p in dict.fromkeys(trace_paths + list(picked)) if any(t["path"] == p for t in tree)][:MAX_FILES_READ]
        files, total = {}, 0
        for p in wanted:
            text = _read(tok, repo, base, p)
            if text and total + len(text) <= MAX_CHARS:
                files[p] = text
                total += len(text)
        if not files:
            raise RepairError("Aucun fichier pertinent lisible dans le dépôt.")
        code = "\n\n".join(f"=== {p} ===\n{t}" for p, t in files.items())
        patch = _claude(RULES, f"{ask}\n\nCODE ACTUEL (branche {base}) :\n{code}\n\nAppelle submit_patch.", PATCH_TOOL, deep=True)
        if patch.get("cannot") and not patch.get("edits") and not patch.get("new_files"):
            raise RepairError("Correction non faite par prudence : " + patch["cannot"][:400])
        changed = apply_edits(files, patch.get("edits") or [], patch.get("new_files") or [])
        branch = f"{BRANCH_PREFIX}{job.kind}-{job.id[:8]}"
        head = _ok(_gh("GET", f"/repos/{repo}/git/ref/heads/{base}", tok), "branche de base")["object"]["sha"]
        base_tree = _ok(_gh("GET", f"/repos/{repo}/git/commits/{head}", tok), "commit de base")["tree"]["sha"]
        tree_sha = _ok(_gh("POST", f"/repos/{repo}/git/trees", tok, json={"base_tree": base_tree, "tree": [
            {"path": p, "mode": "100644", "type": "blob", "content": t} for p, t in changed.items()]}), "arbre")["sha"]
        title = (patch.get("title") or "Correctif UniC AI")[:90]
        commit = _ok(_gh("POST", f"/repos/{repo}/git/commits", tok, json={
            "message": f"{title}\n\n{patch.get('summary', '')}\n\nProposé par UniC AI (atelier d'auto-réparation).",
            "tree": tree_sha, "parents": [head]}), "commit")["sha"]
        _ok(_gh("POST", f"/repos/{repo}/git/refs", tok, json={"ref": f"refs/heads/{branch}", "sha": commit}), "branche")
        body = (f"{patch.get('summary', '')}\n\n**Origine** : {'incident ' + job.incident_id if job.incident_id else job.request[:400]}\n\n"
                "Proposé par UniC AI. Les tests tournent sur cette branche ; la fusion se fait seulement au clic du patron.")
        pr = _ok(_gh("POST", f"/repos/{repo}/pulls", tok, json={"title": title, "head": branch, "base": base, "body": body}), "pull request")
        job.status, job.summary, job.branch = "proposed", patch.get("summary", "")[:3000], branch
        job.pr_number, job.pr_url = pr.get("number", 0), pr.get("html_url", "")
        job.files = json.dumps(sorted(changed), ensure_ascii=False)
        job.request = job.request or title
        if job.incident_id:
            i = db.get(Incident, job.incident_id)
            if i is not None:
                i.status, i.fix_url = "fixing", job.pr_url
    except RepairError as exc:
        job.status, job.error = "failed", str(exc)[:1000]
    except Exception as exc:   # jamais de trace brute vers le patron
        logger.exception("Atelier : échec inattendu")
        job.status, job.error = "failed", f"Échec inattendu ({type(exc).__name__})."
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return job


def start_job(db: Session, kind: str, request: str = "", incident_id: str = "") -> RepairJob:
    if kind not in ("fix", "feature"):
        raise RepairError("Type inconnu.")
    if not _token(db):
        raise RepairError("Atelier non connecté à GitHub : Paramètres › Atelier › Connecter GitHub.")
    if is_release_request(request):
        raise RepairError("Ce n'est pas du code : utilise le bloc « Publication » en haut de l'Atelier (déploiement Render, nouvel APK).")
    if not incident_id and len((request or "").strip()) < 10:
        raise RepairError("Décris le problème ou la fonction voulue (une phrase au moins).")
    if incident_id and db.get(Incident, incident_id) is None:
        raise RepairError("Incident introuvable.", 404)
    if db.query(RepairJob).filter(RepairJob.status == "working").count() >= 2:
        raise RepairError("Deux corrections sont déjà en cours : attends qu'elles finissent.")
    job = RepairJob(kind=kind, request=(request or "").strip()[:4000], incident_id=incident_id or "")
    db.add(job)
    db.commit()
    jid = job.id

    def work():
        from app.database import SessionLocal
        s = SessionLocal()
        try:
            j = s.get(RepairJob, jid)
            if j is not None:
                run_job(s, j)
        finally:
            s.close()

    threading.Thread(target=work, name=f"unic-repair-{jid[:8]}", daemon=True).start()
    return job


# ---------- état des tests, fusion, refus ----------

def checks(db: Session, job: RepairJob) -> dict:
    """État des tests GitHub Actions sur la proposition."""
    if not job.pr_number:
        return {"state": "none"}
    tok, repo, _ = _ctx(db)
    pr = _ok(_gh("GET", f"/repos/{repo}/pulls/{job.pr_number}", tok), "pull request")
    if pr.get("merged"):
        return {"state": "merged"}
    if pr.get("state") == "closed":
        return {"state": "closed"}
    runs = _ok(_gh("GET", f"/repos/{repo}/commits/{pr['head']['sha']}/check-runs", tok), "tests").get("check_runs", [])
    runs = [r for r in runs if r.get("name") in REQUIRED_CHECKS]   # les tests (workflow « Tests »), pas l'APK
    if {r.get("name") for r in runs} != set(REQUIRED_CHECKS):
        return {"state": "pending", "detail": "Tests pas encore lancés."}
    if any(r.get("status") != "completed" for r in runs):
        return {"state": "pending", "detail": "Tests en cours…"}
    bad = [r["name"] for r in runs if r.get("conclusion") not in ("success", "skipped", "neutral")]
    return {"state": "failure", "detail": "Échec : " + ", ".join(bad)} if bad else {"state": "success", "detail": "Tous les tests passent."}


def sync(db: Session, job: RepairJob) -> None:
    """La pull request a été fusionnée (ou fermée) sans passer par « Fusionner » (fusion automatique de GitHub) : on aligne la proposition,
    sinon elle resterait « Prête » et la pastille de l'Atelier ne disparaîtrait jamais."""
    if job.status != "proposed" or not job.pr_number:
        return
    state = checks(db, job)["state"]
    if state not in ("merged", "closed"):
        return
    job.status = state
    if job.incident_id:
        i = db.get(Incident, job.incident_id)
        if i is not None and i.status == "fixing":
            i.status, i.fix_url = ("fixed", i.fix_url) if state == "merged" else ("open", "")
    db.commit()


def sync_all(db: Session) -> None:
    for job in db.query(RepairJob).filter(RepairJob.status == "proposed").all():
        try:
            sync(db, job)
        except RepairError:
            return   # GitHub injoignable ou non connecté : l'état reste tel quel


# ---------- publication : déploiement Render et APK ----------

def _deploy_state(head: str) -> dict:
    """Le serveur compare SA version (fournie par Render) à la dernière version du dépôt : pas de supposition."""
    mine = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    if not mine:
        return {"state": "unknown", "detail": "Version du serveur inconnue (hors Render)."}
    if mine == head:
        return {"state": "ok", "detail": "Render a la dernière version."}
    return {"state": "pending", "detail": "Render n'a pas encore la dernière version : déploiement en cours. "
            "Si ça dure plus de 10 minutes : Render › Manual Deploy."}


def release(db: Session) -> dict:
    """État de la publication : version en ligne sur Render et dernier APK construit."""
    tok, repo, base = _ctx(db)
    head = _ok(_gh("GET", f"/repos/{repo}/commits/{base}", tok), "dernière version").get("sha", "")
    out = {"latest": head[:7], "deploy": _deploy_state(head), "apk": {"state": "unknown", "detail": "Aucun APK construit."}}
    r = _gh("GET", f"/repos/{repo}/actions/workflows/android.yml/runs", tok, params={"branch": base, "per_page": 1})
    if r.status_code in (403, 404):
        out["apk"] = {"state": "unknown", "detail": "Le jeton GitHub n'a pas la permission « Actions » : ajoute « Actions : Read and write »."}
        return out
    runs = (r.json() or {}).get("workflow_runs", []) if r.status_code < 300 else []
    if runs:
        run = runs[0]
        done = run.get("status") == "completed"
        ok = done and run.get("conclusion") == "success"
        state = "building" if not done else ("failed" if not ok else ("ready" if run.get("head_sha") == head else "old"))
        out["apk"] = {"state": state, "url": run.get("html_url", ""), "when": run.get("updated_at", ""),
                      "detail": {"building": "APK en construction (3 minutes environ)…", "ready": "APK à jour.",
                                 "old": "Cet APK ne contient pas la dernière version.", "failed": "La construction a échoué."}[state]}
    return out


def build_apk(db: Session) -> dict:
    """Clic du patron : lance la construction de l'APK sur la dernière version. (La fusion automatique de GitHub ne la déclenche pas.)"""
    tok, repo, base = _ctx(db)
    r = _gh("POST", f"/repos/{repo}/actions/workflows/android.yml/dispatches", tok, json={"ref": base})
    if r.status_code == 204:
        return {"ok": True, "note": "APK en construction : 3 minutes environ. Le lien apparaît ici."}
    if r.status_code in (403, 404):
        raise RepairError("Le jeton GitHub n'a pas la permission de lancer la construction : "
                          "github.com › Settings › Developer settings › ton jeton › Permissions › « Actions : Read and write ».", 403)
    _ok(r, "construction de l'APK")
    return {"ok": True, "note": "Construction lancée."}


def to_dict(job: RepairJob) -> dict:
    return {"id": job.id, "kind": job.kind, "request": job.request, "status": job.status, "summary": job.summary,
            "files": json.loads(job.files or "[]"), "pr_url": job.pr_url, "pr_number": job.pr_number, "error": job.error,
            "incident_id": job.incident_id, "created_at": job.created_at.isoformat() if job.created_at else None}


def merge(db: Session, job: RepairJob) -> dict:
    """Clic du patron : fusionne SEULEMENT si les tests sont verts, puis lance le redéploiement si un crochet est fourni."""
    if job.status != "proposed":
        raise RepairError("Rien à fusionner.")
    st = checks(db, job)
    if st["state"] != "success":
        raise RepairError("Fusion refusée : les tests ne sont pas verts (" + st.get("detail", st["state"]) + ").", 409)
    tok, repo, _ = _ctx(db)
    _ok(_gh("PUT", f"/repos/{repo}/pulls/{job.pr_number}/merge", tok, json={"merge_method": "squash"}), "fusion")
    _gh("DELETE", f"/repos/{repo}/git/refs/heads/{job.branch}", tok)
    job.status = "merged"
    if job.incident_id:
        i = db.get(Incident, job.incident_id)
        if i is not None:
            i.status = "fixed"
    deployed = False
    hook = _hook(db)
    if hook:
        try:
            with httpx.Client(timeout=20) as c:
                deployed = c.post(hook).status_code < 300
        except httpx.HTTPError:
            deployed = False
    db.commit()
    return {"ok": True, "deployed": deployed,
            "note": "Redéploiement lancé : la correction sera en ligne dans quelques minutes. Pour l'APK : bloc « Publication »." if deployed
            else "Fusionné. Render redéploie tout seul ; sinon lance « Manual Deploy ». Pour l'APK : bloc « Publication »."}


def close(db: Session, job: RepairJob) -> None:
    if job.status == "proposed" and job.pr_number:
        tok, repo, _ = _ctx(db)
        _gh("PATCH", f"/repos/{repo}/pulls/{job.pr_number}", tok, json={"state": "closed"})
        _gh("DELETE", f"/repos/{repo}/git/refs/heads/{job.branch}", tok)
    if job.incident_id:
        i = db.get(Incident, job.incident_id)
        if i is not None and i.status == "fixing":
            i.status, i.fix_url = "open", ""
    job.status = "closed"
    db.commit()
