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
