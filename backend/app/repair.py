"""UniC se corrige et s'améliore lui-même — sans jamais toucher la production sans le clic du patron.

1. Un problème (incident) ou une demande de fonction arrive.
2. Moteur « Claude Code » (par défaut) : le serveur lance .github/workflows/atelier.yml ; Claude Code lit TOUT le dépôt, modifie le
   code, lance les tests, puis le workflow vérifie les garde-fous et pousse une branche à part. Le serveur suit l'exécution et ouvre la
   PULL REQUEST (brouillon). Repli automatique sur le moteur « classique » si le workflow ou la permission Actions manque :
   Claude Opus lit jusqu'à 10 fichiers et écrit le correctif ; le serveur le vérifie (chemins autorisés, remplacements exacts,
   Python qui compile) puis ouvre la pull request. Dans les deux cas, la production ne change pas.
4. GitHub Actions lance tous les tests sur cette branche.
5. Le patron voit le résumé et l'état des tests ; « Fusionner » n'est possible que si les tests sont verts.
   Après fusion, Render redéploie (crochet de déploiement si fourni, sinon « Manual Deploy »).

Le jeton GitHub (accès au seul dépôt de l'appli) est chiffré (secrets_box), jamais renvoyé ni écrit dans un journal.
Zones protégées (sécurité, secrets, déploiement, ce mécanisme lui-même) : jamais modifiées par l'IA.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import zipfile
from datetime import datetime, timedelta, timezone

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
# Jobs de .github/workflows/tests.yml : TOUS sont exigés (les garde-fous protègent les zones protégées, la qualité cherche les failles).
# Un contrôle absent, ignoré (skipped), neutre, annulé ou en échec ne vaut jamais « vert ».
REQUIRED_CHECKS = ("guardrails", "quality", "backend", "frontend")


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
            "base": deployed_branch() or _get(db, "repair_base") or "", "deploy_hook": bool(_hook(db)), "engine": engine(db)}


# ---------- moteur : Claude Code (GitHub Actions) ou classique ----------

ENGINE_KEY = "atelier_engine"
ENGINES = ("claude_code", "classique")
WORKFLOW = "atelier.yml"
BUDGET_USD = "5"                       # plafond de dépense Claude par tâche (--max-budget-usd)
ASK_MAX = 20_000
POLL_EVERY = timedelta(seconds=30)     # l'écran de l'Atelier se rafraîchit toutes les 8 s : GitHub n'est interrogé qu'une fois sur quatre
LOST_AFTER = timedelta(minutes=20)     # lancement accepté mais aucune exécution visible
MAX_RUN = timedelta(hours=2)
WORKING_NOTE = "Claude Code travaille sur GitHub (5 à 30 minutes) : il lit le dépôt, modifie le code et lance les tests."
STEP_HINTS = {
    "Clé Claude (secret ANTHROPIC_API_KEY)": "Clé Claude absente sur GitHub : github.com › dépôt UniC-Plaquiste-IA › Settings › Secrets and "
                                             "variables › Actions › New repository secret › nom ANTHROPIC_API_KEY.",
    "Claude Code travaille": "Claude Code n'a pas terminé (plafond de dépense atteint ou erreur).",
    "Modification préparée": "Modification trop grosse pour être proposée.",
    "Garde-fous (zones protégées)": "Refusé par les garde-fous : la modification touchait une zone protégée ou supprimait un fichier essentiel.",
    "Publication de la branche": "GitHub a refusé la publication de la branche (elle existe peut-être déjà).",
}


def engine(db: Session) -> str:
    v = _get(db, ENGINE_KEY)
    return v if v in ENGINES else "claude_code"


def set_engine(db: Session, value: str) -> str:
    """Choix du patron : « claude_code » (par défaut) ou « classique » (l'ancien moteur, sans GitHub Actions)."""
    if value not in ENGINES:
        raise RepairError("Moteur inconnu : « claude_code » ou « classique ».")
    _put(db, ENGINE_KEY, value)
    return value


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


def _ask(db: Session, job: RepairJob) -> tuple[str, list[str]]:
    problem, trace_paths = _incident_text(db, job)
    ask = problem or f"DEMANDE DU PATRON ({'nouvelle fonction' if job.kind == 'feature' else 'problème signalé'}) :\n{job.request}"
    if problem and job.request:
        ask += f"\n\nPRÉCISION DU PATRON : {job.request}"
    return ask, trace_paths


def _branch(job: RepairJob) -> str:
    return f"{BRANCH_PREFIX}{job.kind}-{job.id[:8]}"


def _dispatch(job: RepairJob, tok: str, repo: str, base: str, ask: str) -> bool:
    """Confie la tâche à Claude Code (workflow atelier.yml). False si le dépôt ou le jeton ne le permet pas : le moteur classique prend le relais."""
    from app.config import settings
    r = _gh("POST", f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches", tok, json={"ref": base, "inputs": {
        "job_id": job.id, "branch": _branch(job), "request": ask[:ASK_MAX], "model": settings.anthropic_model, "budget": BUDGET_USD}})
    if r.status_code != 204:
        logger.warning("Atelier : Claude Code indisponible (GitHub %s), moteur classique", r.status_code)
        return False
    job.branch, job.summary = _branch(job), WORKING_NOTE
    return True


def _open_pr(db: Session, job: RepairJob, tok: str, repo: str, base: str, title: str, summary: str, files: list[str]) -> None:
    body = (f"{summary}\n\n**Origine** : {'incident ' + job.incident_id if job.incident_id else job.request[:400]}\n\n"
            "Proposé par UniC AI. Les tests tournent sur cette branche ; la fusion se fait seulement au clic du patron.")
    # déjà ouverte (deux écrans ouverts en même temps, ou nouvel essai après une coupure) : on la reprend au lieu d'en ouvrir une seconde
    owner = repo.split("/", 1)[0]
    same = _ok(_gh("GET", f"/repos/{repo}/pulls", tok, params={"head": f"{owner}:{job.branch}", "state": "all"}), "pull request")
    # BROUILLON : la fusion automatique du dépôt (automerge.yml) ignore les brouillons ; seul le clic « Fusionner » du patron la publie
    pr = same[0] if isinstance(same, list) and same else _ok(_gh("POST", f"/repos/{repo}/pulls", tok, json={
        "title": title[:90], "head": job.branch, "base": base, "body": body, "draft": True}), "pull request")
    job.status, job.summary = "proposed", summary[:3000]
    job.pr_number, job.pr_url = pr.get("number", 0), pr.get("html_url", "")
    job.files = json.dumps(sorted(f for f in files if f), ensure_ascii=False)
    job.request = job.request or title[:4000]
    if job.incident_id:
        i = db.get(Incident, job.incident_id)
        if i is not None:
            i.status, i.fix_url = "fixing", job.pr_url


def run_job(db: Session, job: RepairJob, claude_code: bool = False) -> RepairJob:
    """Du problème à la pull request. Toute erreur laisse le job « failed » avec une explication.
    claude_code=True (demande faite dans UniC Code) : Claude Code obligatoirement, jamais le repli sur le moteur classique."""
    try:
        tok, repo, base = _ctx(db)
        ask, trace_paths = _ask(db, job)
        if claude_code:
            if not _dispatch(job, tok, repo, base, ask):
                raise RepairError("Claude Code n'a pas pu démarrer sur GitHub : workflow atelier.yml absent, ou jeton sans la permission "
                                  "« Actions : Read and write ».", 503)
        elif not (engine(db) == "claude_code" and _dispatch(job, tok, repo, base, ask)):
            _classic(db, job, tok, repo, base, ask, trace_paths)
    except RepairError as exc:
        job.status, job.error = "failed", str(exc)[:1000]
    except Exception as exc:   # jamais de trace brute vers le patron
        logger.exception("Atelier : échec inattendu")
        job.status, job.error = "failed", f"Échec inattendu ({type(exc).__name__})."
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    return job


def _classic(db: Session, job: RepairJob, tok: str, repo: str, base: str, ask: str, trace_paths: list[str]) -> None:
    """Moteur classique : Claude lit jusqu'à 10 fichiers et rend des remplacements exacts, que le serveur vérifie et publie."""
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
    branch = _branch(job)
    head = _ok(_gh("GET", f"/repos/{repo}/git/ref/heads/{base}", tok), "branche de base")["object"]["sha"]
    base_tree = _ok(_gh("GET", f"/repos/{repo}/git/commits/{head}", tok), "commit de base")["tree"]["sha"]
    tree_sha = _ok(_gh("POST", f"/repos/{repo}/git/trees", tok, json={"base_tree": base_tree, "tree": [
        {"path": p, "mode": "100644", "type": "blob", "content": t} for p, t in changed.items()]}), "arbre")["sha"]
    title = (patch.get("title") or "Correctif UniC AI")[:90]
    commit = _ok(_gh("POST", f"/repos/{repo}/git/commits", tok, json={
        "message": f"{title}\n\n{patch.get('summary', '')}\n\nProposé par UniC AI (atelier d'auto-réparation).",
        "tree": tree_sha, "parents": [head]}), "commit")["sha"]
    _ok(_gh("POST", f"/repos/{repo}/git/refs", tok, json={"ref": f"refs/heads/{branch}", "sha": commit}), "branche")
    job.branch = branch
    _open_pr(db, job, tok, repo, base, title, patch.get("summary", ""), list(changed))


def start_job(db: Session, kind: str, request: str = "", incident_id: str = "", claude_code: bool = False) -> RepairJob:
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
                run_job(s, j, claude_code)
        finally:
            s.close()

    threading.Thread(target=work, name=f"unic-repair-{jid[:8]}", daemon=True).start()
    return job


# ---------- état des tests, fusion, refus ----------

def _test_runs(tok: str, repo: str, sha: str) -> list[dict]:
    """Tests du commit. Un jeton GitHub « fine-grained » n'a pas la permission Checks : on lit alors les jobs du workflow « Tests »
    par l'API Actions (permission « Actions : lecture » suffit)."""
    r = _gh("GET", f"/repos/{repo}/commits/{sha}/check-runs", tok)
    if r.status_code < 300:
        return r.json().get("check_runs", [])
    runs = _ok(_gh("GET", f"/repos/{repo}/actions/runs", tok, params={"head_sha": sha, "per_page": 20}), "tests").get("workflow_runs", [])
    tests = [w for w in runs if w.get("name") == "Tests"]   # la plus récente d'abord
    # le run de la pull request (seul à contenir « guardrails ») avant un éventuel run « push »
    latest = next((w for w in tests if w.get("event") == "pull_request"), None) or (tests[0] if tests else None)
    if latest is None:
        return []
    jobs = _ok(_gh("GET", f"/repos/{repo}/actions/runs/{latest['id']}/jobs", tok), "tests").get("jobs", [])
    return [{"name": j.get("name"), "status": j.get("status"), "conclusion": j.get("conclusion")} for j in jobs]


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
    sha = pr["head"]["sha"]
    runs = [r for r in _test_runs(tok, repo, sha) if r.get("name") in REQUIRED_CHECKS]   # les tests (workflow « Tests »), pas l'APK
    seen = {r.get("name") for r in runs}
    if seen != set(REQUIRED_CHECKS):
        absent = ", ".join(n for n in REQUIRED_CHECKS if n not in seen)
        return {"state": "pending", "sha": sha, "detail": f"Contrôles pas encore lancés ou absents : {absent}."}
    if any(r.get("status") != "completed" for r in runs):
        return {"state": "pending", "sha": sha, "detail": "Tests en cours…"}
    bad = sorted({f"{r['name']} ({r.get('conclusion') or 'sans résultat'})" for r in runs if r.get("conclusion") != "success"})   # skipped, neutral, cancelled… : refusés
    if bad:
        return {"state": "failure", "sha": sha, "detail": "Échec ou contrôle ignoré : " + ", ".join(bad)}
    return {"state": "success", "sha": sha, "detail": "Tous les contrôles passent."}


# ---------- suivi d'une tâche confiée à Claude Code ----------

def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _find_run(tok: str, repo: str, job: RepairJob) -> dict | None:
    runs = _ok(_gh("GET", f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs", tok, params={"event": "workflow_dispatch", "per_page": 30}),
               "suivi de Claude Code").get("workflow_runs", [])
    return next((r for r in runs if r.get("display_title") == f"Atelier {job.id}"), None)


def _failed_step(tok: str, repo: str, run_id: int) -> str:
    try:
        jobs = _ok(_gh("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs", tok), "étapes").get("jobs", [])
    except RepairError:
        return ""
    return next((s.get("name", "") for j in jobs for s in (j.get("steps") or []) if s.get("conclusion") == "failure"), "")


def _run_note(tok: str, repo: str, run_id: int) -> str:
    """Explication écrite par Claude Code (artefact « atelier », fichier summary.md). Vide si illisible : ce n'est qu'un plus."""
    try:
        arts = _ok(_gh("GET", f"/repos/{repo}/actions/runs/{run_id}/artifacts", tok), "résumé").get("artifacts", [])
        art = next((a for a in arts if a.get("name") == "atelier" and not a.get("expired")), None)
        if art is None:
            return ""
        r = _gh("GET", f"/repos/{repo}/actions/artifacts/{art['id']}/zip", tok, follow_redirects=True)
        if r.status_code >= 300 or len(r.content) > 8_000_000:
            return ""
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            info = z.getinfo("summary.md")
            if info.file_size > 200_000:
                return ""
            return z.read(info).decode("utf-8", "replace").strip()[:3000]
    except (RepairError, KeyError, ValueError, zipfile.BadZipFile):
        return ""


def _follow(db: Session, job: RepairJob) -> None:
    """Tâche confiée à Claude Code : suit l'exécution sur GitHub. À la fin, ouvre la proposition (brouillon) ou explique l'échec."""
    now = datetime.now(timezone.utc)
    if now - (_aware(job.updated_at) or now - POLL_EVERY) < POLL_EVERY:
        return
    tok, repo, base = _ctx(db)
    run = _find_run(tok, repo, job)
    age = now - (_aware(job.created_at) or now)
    job.updated_at = now
    if run is None or run.get("status") != "completed":
        if run is None and age > LOST_AFTER:
            job.status, job.error = "failed", "Claude Code n'a pas démarré sur GitHub. Relance la demande."
        elif age > MAX_RUN:
            if run is not None:
                _gh("POST", f"/repos/{repo}/actions/runs/{run.get('id')}/cancel", tok)
            job.status, job.error = "failed", "Claude Code a dépassé 2 heures : tâche arrêtée."
        db.commit()
        return
    url = run.get("html_url", "")
    if run.get("conclusion") != "success":
        step = _failed_step(tok, repo, run.get("id", 0))
        note = _run_note(tok, repo, run.get("id", 0))
        why = STEP_HINTS.get(step) or (f"Étape « {step} » en échec." if step else f"Exécution {run.get('conclusion') or 'interrompue'}.")
        job.status, job.error = "failed", (why + (f"\n\nExplication de Claude : {note}" if note else "") + f"\n\nDétail : {url}")[:1000]
        db.commit()
        return
    ref = _gh("GET", f"/repos/{repo}/git/ref/heads/{job.branch}", tok)
    if ref.status_code == 404:
        note = _run_note(tok, repo, run.get("id", 0))
        job.status, job.error = "failed", ("Claude Code n'a rien modifié." + (f"\n\nSon explication : {note}" if note else "")
                                           + f"\n\nDétail : {url}")[:1000]
        db.commit()
        return
    sha = _ok(ref, "branche de la proposition")["object"]["sha"]
    message = _ok(_gh("GET", f"/repos/{repo}/git/commits/{sha}", tok), "commit").get("message", "")
    title, _, rest = message.partition("\n")
    rest = rest.replace("Proposé par UniC AI (Atelier, Claude Code).", "").strip()
    files = [f.get("filename", "") for f in _ok(_gh("GET", f"/repos/{repo}/compare/{base}...{job.branch}", tok), "comparaison").get("files", [])]
    _open_pr(db, job, tok, repo, base, title.strip() or "Proposition UniC AI", rest or WORKING_NOTE, files)
    db.commit()


def sync(db: Session, job: RepairJob) -> None:
    """Tâche confiée à Claude Code : suivi de l'exécution. Proposition fusionnée (ou fermée) sans passer par « Fusionner » (fusion
    automatique de GitHub) : on l'aligne, sinon elle resterait « Prête » et la pastille de l'Atelier ne disparaîtrait jamais."""
    if job.status == "working" and job.branch:
        _follow(db, job)
        return
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
    for job in db.query(RepairJob).filter(RepairJob.status.in_(("proposed", "working"))).all():
        try:
            sync(db, job)
        except RepairError:
            return   # GitHub injoignable ou non connecté : l'état reste tel quel
        except (KeyError, TypeError, ValueError):   # réponse GitHub inattendue pour UNE tâche : les autres restent suivies
            logger.warning("Atelier : suivi impossible pour %s", job.id[:8])
            db.rollback()


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


def _ready(tok: str, repo: str, number: int) -> None:
    """Sort la proposition du mode brouillon (API GraphQL : l'API REST ne le permet pas). Sans effet si elle n'en est pas un."""
    pr = _ok(_gh("GET", f"/repos/{repo}/pulls/{number}", tok), "pull request")
    if not pr.get("draft"):
        return
    r = _gh("POST", "/graphql", tok, json={"query": "mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) "
                                                     "{ pullRequest { isDraft } } }", "variables": {"id": pr.get("node_id", "")}})
    data = _ok(r, "sortie du brouillon")
    if data.get("errors"):
        raise RepairError("GitHub refuse de sortir la proposition du brouillon : " + str(data["errors"][0].get("message", ""))[:160], 502)


def merge(db: Session, job: RepairJob) -> dict:
    """Clic du patron : fusionne SEULEMENT si les tests sont verts, puis lance le redéploiement si un crochet est fourni."""
    if job.status != "proposed":
        raise RepairError("Rien à fusionner.")
    st = checks(db, job)
    if st["state"] != "success":
        raise RepairError("Fusion refusée : les tests ne sont pas verts (" + st.get("detail", st["state"]) + ").", 409)
    tok, repo, _ = _ctx(db)
    _ready(tok, repo, job.pr_number)   # brouillon → prête, juste avant la fusion (GitHub refuse de fusionner un brouillon)
    # « sha » = le commit exact qui a passé les contrôles : si la proposition a bougé depuis, GitHub refuse (409) au lieu de fusionner du code non testé
    r = _gh("PUT", f"/repos/{repo}/pulls/{job.pr_number}/merge", tok, json={"merge_method": "squash", "sha": st["sha"]})
    if r.status_code == 409:
        raise RepairError("Fusion refusée : la proposition a changé depuis les contrôles. Attends les nouveaux contrôles, puis réessaie.", 409)
    _ok(r, "fusion")
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
    if job.status == "working" and job.branch:   # Claude Code travaille encore : on l'arrête, rien ne sera proposé
        try:
            tok, repo, _ = _ctx(db)
            run = _find_run(tok, repo, job)
            if run is not None and run.get("status") != "completed":
                _gh("POST", f"/repos/{repo}/actions/runs/{run.get('id')}/cancel", tok)
            _gh("DELETE", f"/repos/{repo}/git/refs/heads/{job.branch}", tok)
        except RepairError:
            pass
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
