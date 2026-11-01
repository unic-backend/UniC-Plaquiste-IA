"""UniC Code : le moteur Claude Code pour tout ce qu'il sait faire. Un projet part au workflow unic-code.yml (aucun accès au dépôt),
est suivi jusqu'à la livraison (ZIP + aperçu isolé) ou l'échec expliqué ; une suite reprend le projet livré ; le code de l'IA passe
toujours par Claude Code. Le workflow : jeton « actions : read » seulement, pas de checkout, entrées jamais recopiées dans un script."""
import io
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "unic-code.yml"
GAME = "<!doctype html><html><body><canvas id=c></canvas><script>document.title='Memory'</script></body></html>"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class R:
    def __init__(self, code, data=None, content=None):
        self.status_code, self._d = code, data if data is not None else {}
        self.content = content if content is not None else b"x"

    def json(self):
        return self._d


@pytest.fixture
def db(client):
    from app import repair, secrets_box
    from app.database import SessionLocal
    from app.models import CodeTask
    s = SessionLocal()
    repair._put(s, "repair_gh_token", secrets_box.encrypt("ghp_" + "z" * 30))
    repair._put(s, "repair_base", "main")
    s.query(CodeTask).delete()
    s.commit()
    yield s
    s.rollback()
    s.query(CodeTask).delete()
    s.commit()
    s.close()


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def _task(db, *, status="working", minutes=1, **kw):
    from app.models import CodeTask
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    t = CodeTask(request="Un jeu de memory pour enfants", status=status, created_at=created, updated_at=created, **kw)
    db.add(t)
    db.commit()
    return t


def _world(monkeypatch, *, task=None, run=None, steps=(), arts=None, project=None, summary="", dispatch=204):
    from app import repair
    calls = []

    def gh(method, path, token, **kw):
        calls.append((method, path, kw))
        if path.endswith("/actions/workflows/unic-code.yml/dispatches"):
            return R(dispatch, content=b"")
        if path.endswith("/actions/workflows/unic-code.yml/runs"):
            return R(200, {"workflow_runs": [{"id": 1, "display_title": "UniC Code autre", "status": "completed"}] + ([run] if run else [])})
        if path.endswith("/jobs"):
            return R(200, {"jobs": [{"steps": [{"name": n, "conclusion": c} for n, c in steps]}]})
        if path.endswith("/artifacts"):
            return R(200, {"artifacts": arts if arts is not None else []})
        if path.endswith("/artifacts/11/zip"):
            assert kw.get("follow_redirects") is True
            return R(200, content=_zip({"summary.md": summary}))
        if path.endswith("/artifacts/12/zip"):
            return R(200, content=project if project is not None else _zip({"README.md": "# Memory", "apercu.html": GAME, "src/jeu.js": "x"}))
        return R(200)
    monkeypatch.setattr(repair, "_gh", gh)
    return calls


ARTS = [{"id": 11, "name": "resume", "expired": False}, {"id": 12, "name": "projet", "expired": False, "size_in_bytes": 900}]


def test_un_projet_part_a_claude_code_sans_acces_au_depot(client, db, monkeypatch):
    from app.config import settings
    from app.models import CodeTask
    calls = _world(monkeypatch)
    r = client.post("/api/code/projects", json={"request": "Un site vitrine pour une boulangerie à Dakar", "budget": "10"})
    assert r.status_code == 200, r.text
    task = db.get(CodeTask, r.json()["id"])
    assert task.status == "working" and task.budget == "10"
    (method, path, kw), = [c for c in calls if c[1].endswith("/dispatches")]
    inputs = kw["json"]["inputs"]
    assert kw["json"]["ref"] == "main" and inputs["task_id"] == task.id and inputs["budget"] == "10" and inputs["parent_run"] == ""
    assert "boulangerie" in inputs["request"] and inputs["model"] == settings.anthropic_model
    for bad, code in (({"request": "court"}, 400), ({"request": "Un jeu de dames complet", "budget": "500"}, 400)):
        assert client.post("/api/code/projects", json=bad).status_code == code


def test_rien_n_est_enregistre_si_github_refuse(client, db, monkeypatch):
    from app.models import CodeTask
    _world(monkeypatch, dispatch=404)
    r = client.post("/api/code/projects", json={"request": "Un jeu de dames complet pour mobile"})
    assert r.status_code == 503 and "unic-code.yml" in r.json()["detail"]
    assert db.query(CodeTask).count() == 0
    _world(monkeypatch, dispatch=403)
    assert "Actions : Read and write" in client.post("/api/code/projects", json={"request": "Un jeu de dames complet"}).json()["detail"]


def test_deux_projets_en_cours_au_plus(client, db, monkeypatch):
    _task(db)
    _task(db)
    _world(monkeypatch)
    r = client.post("/api/code/projects", json={"request": "Un troisième projet en même temps"})
    assert r.status_code == 409


def test_livraison_resume_fichiers_et_apercu(client, db, monkeypatch):
    from app import code_tasks
    t = _task(db)
    run = {"id": 500, "display_title": f"UniC Code {t.id}", "status": "completed", "conclusion": "success", "html_url": "https://gh/run/500"}
    _world(monkeypatch, run=run, arts=ARTS, summary="Jeu de memory\n\nUn jeu de 12 cartes.\nTests : node test.js OK.\n\nCoût Claude : 0.84 USD")
    code_tasks.follow_all(db)
    assert t.status == "done" and t.title == "Jeu de memory" and t.run_id == 500 and t.artifact_id == 12
    assert "12 cartes" in t.summary and "0.84 USD" in t.summary
    assert t.preview == GAME and code_tasks.to_dict(t)["files"] == ["README.md", "apercu.html", "src/jeu.js"]
    data = client.get("/api/code").json()
    p = next(x for x in data["projects"] if x["id"] == t.id)
    assert p["preview"] is True and p["zip"] is True and "preview" not in str(p.get("summary"))
    z = client.get(f"/api/code/projects/{t.id}/zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip" and "UniC-Code-Jeu-de-memory.zip" in z.headers["content-disposition"]


def test_l_apercu_est_isole_et_le_lien_expire(client, db):
    from app import code_tasks
    t = _task(db, status="done", preview=GAME)
    path = client.get(f"/api/code/projects/{t.id}/preview-link").json()["path"]
    r = client.get(path)
    assert r.status_code == 200 and "<canvas" in r.text
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox allow-scripts") and "allow-same-origin" not in csp     # origine opaque : rien de l'appli n'est lisible
    assert "connect-src 'none'" in csp and "default-src 'none'" in csp and r.headers["cache-control"] == "no-store"
    assert client.get(f"/api/code/apercu/{t.id}?t=faux").status_code == 403
    other = _task(db, status="done", preview="<p>autre</p>")
    assert client.get(path.replace(t.id, other.id)).status_code == 403                    # un lien n'ouvre que SON projet
    old = code_tasks.preview_token(t, now=time.time() - 2 * code_tasks.PREVIEW_TTL)
    assert not code_tasks.preview_ok(t.id, old)


def test_les_echecs_sont_expliques(db, monkeypatch):
    from app import code_tasks
    t = _task(db)
    run = {"id": 501, "display_title": f"UniC Code {t.id}", "status": "completed", "conclusion": "failure", "html_url": "https://gh/run/501"}
    _world(monkeypatch, run=run, steps=[("Clé Claude (secret ANTHROPIC_API_KEY)", "failure")], arts=[])
    code_tasks.follow(db, t)
    assert t.status == "failed" and "ANTHROPIC_API_KEY" in t.error and "https://gh/run/501" in t.error

    t = _task(db)
    run = {"id": 502, "display_title": f"UniC Code {t.id}", "status": "completed", "conclusion": "success", "html_url": "u"}
    _world(monkeypatch, run=run, arts=[ARTS[0]], summary="Impossible\n\nLa demande demande un compte bancaire.")
    code_tasks.follow(db, t)
    assert t.status == "failed" and "aucun fichier" in t.error and "compte bancaire" in t.summary

    lost = _task(db, minutes=30)
    _world(monkeypatch)
    code_tasks.follow(db, lost)
    assert lost.status == "failed" and "n'a pas démarré" in lost.error
    young = _task(db, minutes=2)
    code_tasks.follow(db, young)
    assert young.status == "working"
    young.updated_at = datetime.now(timezone.utc)
    db.commit()
    calls = _world(monkeypatch)
    code_tasks.follow(db, young)
    assert calls == []                                                          # vérifié il y a moins de 30 s : GitHub pas réinterrogé


def test_une_suite_reprend_le_projet_livre(client, db, monkeypatch):
    t = _task(db, status="done", run_id=500, artifact_id=12)
    calls = _world(monkeypatch)
    r = client.post("/api/code/projects", json={"request": "Ajoute un niveau difficile et un chrono", "parent_id": t.id})
    assert r.status_code == 200 and r.json()["parent_id"] == t.id
    inputs = next(kw["json"]["inputs"] for m, p, kw in calls if p.endswith("/dispatches"))
    assert inputs["parent_run"] == "500" and "SUITE DU PROJET" in inputs["request"] and "memory" in inputs["request"]
    unfinished = _task(db)
    assert client.post("/api/code/projects", json={"request": "Suite impossible ici", "parent_id": unfinished.id}).status_code == 404


def test_arreter_et_supprimer(client, db, monkeypatch):
    t = _task(db)
    run = {"id": 503, "display_title": f"UniC Code {t.id}", "status": "in_progress"}
    calls = _world(monkeypatch, run=run)
    assert client.delete(f"/api/code/projects/{t.id}").status_code == 409          # en cours : on l'arrête d'abord
    assert client.post(f"/api/code/projects/{t.id}/close").json()["status"] == "closed"
    assert any(m == "POST" and p.endswith("/actions/runs/503/cancel") for m, p, kw in calls)
    assert client.delete(f"/api/code/projects/{t.id}").json() == {"ok": True}


def test_le_code_de_l_ia_passe_toujours_par_claude_code(db, monkeypatch):
    from app import repair
    from app.models import RepairJob
    repair._put(db, repair.ENGINE_KEY, "classique")                           # l'Atelier est réglé sur le moteur classique…
    db.commit()
    seen = []

    def gh(method, path, token, **kw):
        seen.append(path)
        return R(404 if path.endswith("/dispatches") else 200)
    monkeypatch.setattr(repair, "_gh", gh)
    monkeypatch.setattr(repair, "_claude", lambda *a, **k: (_ for _ in ()).throw(AssertionError("moteur classique interdit")))
    job = RepairJob(kind="fix", request="Corrige le total des factures")
    db.add(job)
    db.commit()
    repair.run_job(db, job, claude_code=True)                                   # …UniC Code passe quand même par Claude Code
    assert any(p.endswith("/actions/workflows/atelier.yml/dispatches") for p in seen)
    assert job.status == "failed" and "Claude Code n'a pas pu démarrer" in job.error    # workflow absent : échec expliqué, pas de repli
    repair._put(db, repair.ENGINE_KEY, "")
    db.delete(job)
    db.commit()


def test_mon_ia_lance_claude_code_et_reste_dans_unic_code(client, db, monkeypatch):
    from app import repair
    from app.models import RepairJob
    started = []
    monkeypatch.setattr(repair, "run_job", lambda s, j, claude_code=False, budget="5": started.append((j.id, claude_code, budget)))
    r = client.post("/api/code/app", json={"kind": "feature", "request": "Ajoute un export Excel des pointages", "budget": "10"})
    assert r.status_code == 200 and r.json()["engine"] == "claude_code"
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started == [(r.json()["id"], True, "10")]
    assert client.post("/api/code/app", json={"kind": "fix", "request": "Corrige le total des factures", "budget": "500"}).status_code == 400
    atelier = RepairJob(kind="fix", request="Correction lancée depuis l'Atelier", status="failed")
    db.add(atelier)
    db.commit()
    code_ids = {j["id"] for j in client.get("/api/code").json()["app_jobs"]}
    atelier_ids = {j["id"] for j in client.get("/api/selfcare").json()["jobs"]}
    assert r.json()["id"] in code_ids and r.json()["id"] not in atelier_ids          # chaque section ne montre que SES tâches
    assert atelier.id in atelier_ids and atelier.id not in code_ids
    db.query(RepairJob).filter(RepairJob.id.in_([r.json()["id"], atelier.id])).delete(synchronize_session=False)
    db.commit()


def test_workflow_unic_code_sans_acces_au_depot():
    text = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    assert set(on["workflow_dispatch"]["inputs"]) == {"task_id", "request", "model", "budget", "parent_run"}
    assert wf["run-name"] == "UniC Code ${{ inputs.task_id }}"                    # le serveur retrouve SON exécution par ce titre
    assert wf["permissions"] == {}
    job = wf["jobs"]["projet"]
    assert job["permissions"] == {"actions": "read"}                            # ni contents, ni pull-requests, ni écriture
    steps = {s.get("name", s.get("uses", "")): s for s in job["steps"]}
    assert not any(str(s.get("uses", "")).startswith("actions/checkout") for s in job["steps"])   # le code de l'appli n'est jamais là
    for s in job["steps"]:
        assert "${{" not in s.get("run", ""), s.get("name")
        assert "cache" not in (s.get("with") or {})
    cmd = steps["Claude Code travaille"]["run"]
    assert "--max-budget-usd" in cmd and "apercu.html" in cmd
    tools = re.search(r'--allowedTools "([^"]+)"', cmd).group(1).split(",")
    assert "Bash" not in tools and not any(t.startswith(("Bash(git", "Bash(curl", "Bash(wget", "Bash(gh", "WebFetch")) for t in tools)
    assert re.search(r"@anthropic-ai/claude-code@\d+\.\d+\.\d+\b", steps["Outils"]["run"])
    assert steps["Projet précédent"]["with"]["run-id"] == "${{ inputs.parent_run }}"
    livraison = steps["Livraison du projet"]["with"]
    assert livraison["name"] == "projet" and "node_modules" in livraison["path"] and livraison["if-no-files-found"] == "error"
    from app import code_tasks
    assert set(code_tasks.STEP_HINTS) <= set(steps)                              # chaque explication au patron vise une vraie étape


# ---------- une seule zone de saisie : le serveur choisit entre « projet » et « code de l'IA » ----------

def _claude_says(monkeypatch, text="", available=True, boom=False):
    from app.ai import PROVIDERS, AIResult
    seen = []

    def fake(self, messages, **kw):
        seen.append((messages, kw))
        if boom:
            raise RuntimeError("réseau")
        return AIResult(text, "claude", kw.get("model", ""), available and bool(text), "" if text else "claude: crédit épuisé")
    # au niveau de la CLASSE, comme les autres tests : un faux posé sur l'instance resterait en place et masquerait leurs faux
    monkeypatch.setattr(type(PROVIDERS["claude"]), "complete", fake)
    return seen


def test_le_classement_demande_un_mot_a_claude_puis_replie_sur_les_mots(monkeypatch):
    from app import code_tasks as ct
    from app.config import settings
    seen = _claude_says(monkeypatch, "APP")
    assert ct.classify("Fais un jeu de dames") == "app"                       # Claude décide, même sans mot-clé
    messages, kw = seen[0]
    assert kw["model"] == settings.anthropic_fast_model and kw["max_tokens"] <= 16 and messages[0]["role"] == "system"
    _claude_says(monkeypatch, "PROJET.")
    assert ct.classify("Corrige le bouton Fusionner dans l'Atelier") == "projet"
    for kw in ({"text": ""}, {"text": "Je ne sais pas"}, {"text": "APP", "available": False}, {"boom": True}):
        _claude_says(monkeypatch, **kw)                                       # Claude muet, incohérent ou en panne : jamais d'erreur
        assert ct.classify("Corrige le bouton Fusionner dans l'Atelier") == "app"
        assert ct.classify("Fais un jeu de memory pour mobile") == "projet"


def test_slash_ia_et_slash_projet_forcent_le_choix(monkeypatch):
    from app import code_tasks as ct
    seen = _claude_says(monkeypatch, "PROJET")
    assert ct.route("/ia ajoute un export Excel des pointages") == ("app", "ajoute un export Excel des pointages")
    assert ct.route("/projet un site pour ma boutique") == ("projet", "un site pour ma boutique")
    assert seen == []                                                         # choix explicite : aucune question à Claude
    assert ct.route("Un site pour ma boutique") == ("projet", "Un site pour ma boutique")
    assert ct.job_kind("Le clavier cache la zone de texte") == "fix" and ct.job_kind("Ajoute un export Excel") == "feature"


def test_une_demande_sur_l_appli_part_a_claude_code_sur_tout_le_depot(client, db, monkeypatch):
    from app import code_tasks as ct
    from app import repair
    from app.models import RepairJob
    monkeypatch.setattr(ct, "classify", lambda request: "app")
    started = []
    monkeypatch.setattr(repair, "run_job", lambda s, j, claude_code=False, budget="5": started.append((j.id, j.kind, claude_code, budget)))
    r = client.post("/api/code/tasks", json={"request": "Le clavier cache la zone de texte dans le chat"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["type"] == "app" and out["engine"] == "claude_code" and out["job_kind"] == "fix"
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started == [(out["id"], "fix", True, ct.BUDGET_DEFAULT)]
    db.query(RepairJob).filter(RepairJob.id == out["id"]).delete(synchronize_session=False)
    db.commit()


def test_un_projet_ou_une_suite_part_au_dossier_vide_sans_classement(client, db, monkeypatch):
    from app import code_tasks as ct
    asked = []
    monkeypatch.setattr(ct, "classify", lambda request: asked.append(request) or "projet")
    calls = _world(monkeypatch)
    r = client.post("/api/code/tasks", json={"request": "Un jeu de memory sur les outils du plaquiste"})
    assert r.status_code == 200 and r.json()["type"] == "project" and asked and r.json()["title"].startswith("Un jeu de memory")
    inputs = next(kw["json"]["inputs"] for m, p, kw in calls if p.endswith("/dispatches"))
    assert inputs["budget"] == ct.BUDGET_DEFAULT and inputs["parent_run"] == ""
    done = _task(db, status="done", run_id=500, artifact_id=12)
    asked.clear()
    r = client.post("/api/code/tasks", json={"request": "Corrige le bouton de l'écran d'accueil", "parent_id": done.id})
    assert r.status_code == 200 and r.json()["parent_id"] == done.id and asked == []   # une suite reste dans son projet
    assert client.post("/api/code/tasks", json={"request": "Suite d'un projet inconnu", "parent_id": "n'existe-pas"}).status_code == 404
    assert client.post("/api/code/tasks", json={"request": "court"}).status_code == 400


def test_la_liste_melange_projets_et_code_de_l_ia_du_plus_recent_au_plus_ancien(client, db):
    from app.models import RepairJob
    old = _task(db, status="done", minutes=300, title="Jeu de memory")
    new = _task(db, minutes=2)
    mine = RepairJob(kind="feature", request="Ajoute un export Excel des pointages. Avec les heures.", status="proposed", engine="claude_code")
    other = RepairJob(kind="fix", request="Correction lancée depuis l'Atelier", status="failed")
    db.add_all([mine, other])
    db.commit()
    items = client.get("/api/code").json()["items"]
    ids = [i["id"] for i in items]
    assert other.id not in ids                                                # le code de l'Atelier reste dans l'Atelier
    assert ids.index(mine.id) < ids.index(new.id) < ids.index(old.id)       # le plus récent d'abord
    by = {i["id"]: i for i in items}
    assert by[mine.id]["type"] == "app" and by[mine.id]["title"] == "Ajoute un export Excel des pointages."
    assert by[old.id]["type"] == "project" and by[old.id]["title"] == "Jeu de memory"
    assert by[new.id]["title"].startswith("Un jeu de memory")                 # pas encore de titre : la demande
    db.query(RepairJob).filter(RepairJob.id.in_([mine.id, other.id])).delete(synchronize_session=False)
    db.commit()
