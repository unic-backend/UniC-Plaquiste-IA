"""UniC Code · Mon IA : moteur Claude Code (workflow .github/workflows/atelier.yml). Le serveur lui confie la tâche, suit l'exécution sur
GitHub, ouvre la proposition en BROUILLON quand il a fini (ou explique l'échec). L'Atelier, lui, garde son moteur classique.
Le workflow lui-même : jeton en lecture pour Claude, garde-fous de la base avant toute publication, entrées jamais recopiées dans un script."""
import io
import os
import re
import sys
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

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "atelier.yml"


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
    from app.models import RepairJob
    s = SessionLocal()
    repair._put(s, "repair_gh_token", secrets_box.encrypt("ghp_" + "y" * 30))
    repair._put(s, "repair_base", "main")
    repair._put(s, repair.ENGINE_KEY, "")
    s.commit()
    yield s
    s.query(RepairJob).filter(RepairJob.request.like("[cc]%")).delete(synchronize_session=False)
    repair._put(s, repair.ENGINE_KEY, "")
    s.commit()
    s.close()


def _job(db, *, status="working", minutes=1, branch=True):
    from app import repair
    from app.models import RepairJob
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    j = RepairJob(kind="feature", request="[cc] Ajoute un bouton export PDF sur la page devis", status=status,
                  created_at=created, updated_at=created)
    db.add(j)
    db.commit()
    if branch:
        j.branch = repair._branch(j)
        db.commit()
    return j


def _zip(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("summary.md", text)
        z.writestr("atelier.patch", "")
    return buf.getvalue()


def _no_classic(monkeypatch):
    from app import repair

    def boom(*a, **k):
        raise AssertionError("le moteur classique ne doit pas tourner")
    monkeypatch.setattr(repair, "_claude", boom)


def test_la_tache_part_a_claude_code_sur_github(db, monkeypatch):
    from app import repair
    from app.config import settings
    calls = []

    def gh(method, path, token, **kw):
        calls.append((method, path, kw))
        return R(204, content=b"") if path.endswith(f"/actions/workflows/{repair.WORKFLOW}/dispatches") else R(200)
    monkeypatch.setattr(repair, "_gh", gh)
    _no_classic(monkeypatch)
    job = _job(db, branch=False)
    repair.run_job(db, job, claude_code=True)
    assert job.status == "working" and job.branch == f"unic-ai/feature-{job.id[:8]}", job.error
    assert job.summary == repair.WORKING_NOTE and not job.pr_number
    (method, path, kw), = calls
    assert method == "POST" and path == f"/repos/{repair.DEFAULT_REPO}/actions/workflows/atelier.yml/dispatches"
    inputs = kw["json"]["inputs"]
    assert kw["json"]["ref"] == "main" and inputs["job_id"] == job.id and inputs["branch"] == job.branch
    assert "bouton export PDF" in inputs["request"] and inputs["model"] == settings.anthropic_model and inputs["budget"] == "5"
    assert repair.status(db)["engine"] == "classique"                         # l'Atelier garde son moteur classique


def test_l_atelier_reste_classique_et_le_repli_marche(db, monkeypatch):
    from app import repair
    for engine, dispatch_code in (("", 204), ("classique", 204), ("claude_code", 404)):
        repair._put(db, repair.ENGINE_KEY, engine)
        db.commit()
        calls = []

        def gh(method, path, token, **kw):
            calls.append(path)
            if path.endswith("/dispatches"):
                return R(dispatch_code, content=b"")
            if path.endswith("/git/trees/main"):
                return R(200, {"tree": [{"type": "blob", "path": "backend/app/calc.py", "size": 30}]})
            if "/git/ref/heads/" in path:
                return R(200, {"object": {"sha": "base1"}})
            if "/git/commits/base1" in path:
                return R(200, {"tree": {"sha": "tree0"}})
            if path.endswith("/git/trees"):
                return R(201, {"sha": "tree1"})
            if path.endswith("/git/commits"):
                return R(201, {"sha": "c1"})
            if path.endswith("/pulls") and method == "POST":
                return R(201, {"number": 8, "html_url": "https://github.com/x/y/pull/8"})
            return R(200, [] if path.endswith("/pulls") else {})
        answers = iter([{"paths": ["backend/app/calc.py"]},
                        {"title": "Garde", "summary": "Correction.", "edits": [{"path": "backend/app/calc.py", "search": "1 / x", "replace": "1 / (x or 1)"}]}])
        monkeypatch.setattr(repair, "_gh", gh)
        monkeypatch.setattr(repair, "_read", lambda tok, repo, base, p: "def f(x):\n    return 1 / x\n")
        monkeypatch.setattr(repair, "_claude", lambda system, user, tool, deep: next(answers))
        job = _job(db, branch=False)
        repair.run_job(db, job)
        assert job.status == "proposed" and job.pr_number == 8, job.error
        assert any(p.endswith("/dispatches") for p in calls) == (engine == "claude_code")   # Atelier : GitHub Actions jamais sollicité


def _follow_world(monkeypatch, job, *, run=None, steps=(), ref_code=200, note="", existing=()):
    from app import repair
    calls = []

    def gh(method, path, token, **kw):
        calls.append((method, path, kw))
        if path.endswith(f"/actions/workflows/{repair.WORKFLOW}/runs"):
            others = [{"id": 1, "display_title": "Atelier autre-tache", "status": "completed", "conclusion": "success"}]
            return R(200, {"workflow_runs": others + ([run] if run else [])})
        if path.endswith("/jobs"):
            return R(200, {"jobs": [{"steps": [{"name": n, "conclusion": c} for n, c in steps]}]})
        if path.endswith("/artifacts"):
            return R(200, {"artifacts": [{"id": 5, "name": "atelier", "expired": False}]} if note else {"artifacts": []})
        if path.endswith("/artifacts/5/zip"):
            assert kw.get("follow_redirects") is True
            return R(200, content=_zip(note))
        if path.endswith(f"/git/ref/heads/{job.branch}"):
            return R(ref_code, {"object": {"sha": "s1"}} if ref_code == 200 else {"message": "Not Found"})
        if path.endswith("/git/commits/s1"):
            return R(200, {"message": "Ajoute l'export PDF des devis\n\nBesoin : exporter.\nTests : 12 passent.\n\n"
                                      "Proposé par UniC AI (Atelier, Claude Code).\n"})
        if "/compare/main..." in path:
            return R(200, {"files": [{"filename": "frontend/src/Devis.tsx"}, {"filename": "backend/tests/test_devis_pdf.py"}]})
        if path.endswith("/pulls") and method == "GET":
            return R(200, list(existing))
        if path.endswith("/pulls") and method == "POST":
            return R(201, {"number": 12, "html_url": "https://github.com/x/y/pull/12"})
        return R(200)
    monkeypatch.setattr(repair, "_gh", gh)
    return calls


def test_le_suivi_ouvre_la_proposition_en_brouillon_quand_claude_code_a_fini(db, monkeypatch):
    from app import repair
    _no_classic(monkeypatch)
    job = _job(db)
    run = {"id": 99, "display_title": f"Atelier {job.id}", "status": "completed", "conclusion": "success", "html_url": "https://gh/run/99"}
    calls = _follow_world(monkeypatch, job, run=run)
    seen, real = [], repair.sync
    monkeypatch.setattr(repair, "sync", lambda d, j: seen.append(j.id))
    repair.sync_all(db)
    assert job.id in seen                                                       # l'écran de l'Atelier suit aussi les tâches en cours
    monkeypatch.setattr(repair, "sync", real)
    repair.sync(db, job)
    assert job.status == "proposed" and job.pr_number == 12, job.error
    assert job.files == '["backend/tests/test_devis_pdf.py", "frontend/src/Devis.tsx"]'
    assert "Tests : 12 passent." in job.summary and "Proposé par" not in job.summary
    pr = next(kw["json"] for m, p, kw in calls if m == "POST" and p.endswith("/pulls"))
    assert pr["draft"] is True and pr["head"] == job.branch and pr["base"] == "main" and pr["title"] == "Ajoute l'export PDF des devis"
    # tout juste vérifiée : GitHub n'est pas réinterrogé à chaque rafraîchissement de l'écran (toutes les 8 s)
    other = _job(db, minutes=0)
    other.updated_at = datetime.now(timezone.utc)
    db.commit()
    calls.clear()
    repair.sync(db, other)
    assert calls == [] and other.status == "working"


def test_une_proposition_deja_ouverte_est_reprise_pas_doublee(db, monkeypatch):
    from app import repair
    job = _job(db)
    run = {"id": 99, "display_title": f"Atelier {job.id}", "status": "completed", "conclusion": "success", "html_url": "u"}
    calls = _follow_world(monkeypatch, job, run=run, existing=[{"number": 5, "html_url": "https://github.com/x/y/pull/5"}])
    repair.sync(db, job)
    assert job.status == "proposed" and job.pr_number == 5
    assert not any(m == "POST" and p.endswith("/pulls") for m, p, kw in calls)


def test_le_suivi_explique_l_echec_au_patron(db, monkeypatch):
    from app import repair
    job = _job(db)
    run = {"id": 99, "display_title": f"Atelier {job.id}", "status": "completed", "conclusion": "failure", "html_url": "https://gh/run/99"}
    _follow_world(monkeypatch, job, run=run, steps=[("Entrées vérifiées", "success"), ("Clé Claude (secret ANTHROPIC_API_KEY)", "failure")])
    repair.sync(db, job)
    assert job.status == "failed" and "ANTHROPIC_API_KEY" in job.error and "Secrets and variables" in job.error and "https://gh/run/99" in job.error

    job = _job(db)
    run = {"id": 98, "display_title": f"Atelier {job.id}", "status": "completed", "conclusion": "failure", "html_url": "u"}
    _follow_world(monkeypatch, job, run=run, steps=[("Garde-fous (zones protégées)", "failure")], note="J'ai dû toucher repair.py.")
    repair.sync(db, job)
    assert "zone protégée" in job.error and "J'ai dû toucher repair.py." in job.error

    job = _job(db)                                       # réussi mais aucune branche : Claude n'a rien changé, il dit pourquoi
    run = {"id": 97, "display_title": f"Atelier {job.id}", "status": "completed", "conclusion": "success", "html_url": "u"}
    _follow_world(monkeypatch, job, run=run, ref_code=404, note="Demande impossible sans toucher la sécurité.")
    repair.sync(db, job)
    assert job.status == "failed" and "rien modifié" in job.error and "sans toucher la sécurité" in job.error


def test_lancement_perdu_tache_en_cours_et_tache_trop_longue(db, monkeypatch):
    from app import repair
    lost = _job(db, minutes=30)
    _follow_world(monkeypatch, lost)
    repair.sync(db, lost)
    assert lost.status == "failed" and "n'a pas démarré" in lost.error

    young = _job(db, minutes=2)
    _follow_world(monkeypatch, young)
    repair.sync(db, young)
    assert young.status == "working"                                            # GitHub n'a pas encore listé l'exécution

    slow = _job(db, minutes=180)
    run = {"id": 77, "display_title": f"Atelier {slow.id}", "status": "in_progress", "html_url": "u"}
    calls = _follow_world(monkeypatch, slow, run=run)
    repair.sync(db, slow)
    assert slow.status == "failed" and "2 heures" in slow.error
    assert ("POST", f"/repos/{repair.DEFAULT_REPO}/actions/runs/77/cancel") in [(m, p) for m, p, kw in calls]


def test_refuser_une_tache_en_cours_arrete_claude_code(db, monkeypatch):
    from app import repair
    job = _job(db)
    run = {"id": 66, "display_title": f"Atelier {job.id}", "status": "in_progress", "html_url": "u"}
    calls = _follow_world(monkeypatch, job, run=run)
    repair.close(db, job)
    done = [(m, p) for m, p, kw in calls]
    assert job.status == "closed"
    assert ("POST", f"/repos/{repair.DEFAULT_REPO}/actions/runs/66/cancel") in done
    assert ("DELETE", f"/repos/{repair.DEFAULT_REPO}/git/refs/heads/{job.branch}") in done


def test_le_patron_choisit_le_moteur(client, db):
    r = client.put("/api/selfcare/engine", json={"engine": "classique"})
    assert r.status_code == 200 and r.json()["engine"] == "classique"
    assert client.put("/api/selfcare/engine", json={"engine": "n'importe quoi"}).status_code == 400
    assert client.put("/api/selfcare/engine", json={"engine": "claude_code"}).json()["engine"] == "claude_code"


def _steps(job):
    return {s.get("name", ""): s for s in job["steps"]}


def test_workflow_claude_code_sans_droit_d_ecrire_et_garde_fous_de_la_base():
    from app import repair
    text = WORKFLOW.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    assert set(on["workflow_dispatch"]["inputs"]) == {"job_id", "branch", "request", "model", "budget"}
    assert wf["run-name"] == "Atelier ${{ inputs.job_id }}"                     # le serveur retrouve SON exécution par ce titre
    assert wf["permissions"] == {"contents": "read"}
    claude, publier = wf["jobs"]["claude"], wf["jobs"]["publier"]
    assert claude["permissions"] == {"contents": "read"} and publier["permissions"] == {"contents": "write"}
    checkout = next(s for s in claude["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["persist-credentials"] is False                     # aucun identifiant git sur le disque pendant que Claude travaille
    for s in claude["steps"]:
        assert "cache" not in (s.get("with") or {})                             # pas de cache réutilisable par les autres contrôles
    for job in (claude, publier):
        for s in job["steps"]:
            assert "${{" not in s.get("run", ""), s.get("name")                 # entrées et contexte : seulement par variables d'environnement
    cmd = _steps(claude)["Claude Code travaille"]["run"]
    assert "--max-budget-usd" in cmd and "--permission-mode acceptEdits" in cmd
    tools = re.search(r'--allowedTools "([^"]+)"', cmd).group(1).split(",")
    assert "Bash" not in tools and not any(t.startswith(("Bash(git push", "Bash(git commit", "Bash(curl", "Bash(gh")) for t in tools)
    assert re.search(r"@anthropic-ai/claude-code@\d+\.\d+\.\d+\b", _steps(claude)["Outils pour les tests"]["run"])   # version figée
    guard = _steps(publier)["Garde-fous (zones protégées)"]["run"]
    assert 'git checkout "origin/$BASE" -- scripts/guardrails.py scripts/core_manifest.txt' in guard and "python3 -I scripts/guardrails.py" in guard
    names = list(_steps(publier))
    assert names.index("Garde-fous (zones protégées)") < names.index("Publication de la branche")
    every = set(_steps(claude)) | set(names)
    assert set(repair.STEP_HINTS) <= every                                      # chaque explication au patron vise une vraie étape
