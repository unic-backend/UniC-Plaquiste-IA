"""Garde-fous du dépôt (scripts/guardrails.py) : la base ne se perd pas, ne se double pas, les zones protégées restent au propriétaire."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("guardrails", Path(__file__).resolve().parents[2] / "scripts" / "guardrails.py")
g = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(g)

TREE = ["backend/app/main.py", "backend/app/agent.py", "backend/app/auth.py", "backend/tests/test_api.py", "frontend/src/App.tsx",
        "frontend/package.json", "Dockerfile", "docker-compose.yml", "AGENTS.md", "scripts/guardrails.py"]
MANIFEST = ["backend/app/agent.py", "frontend/src/App.tsx"]


def run(changes, labels=(), tree=TREE, files=None, manifest=MANIFEST):
    files = files or {}
    return g.check(changes, set(labels), tree, lambda p: files.get(p, ""), manifest)


def test_normal_extension_passes():
    assert run([("M", "backend/app/agent.py"), ("A", "backend/app/new_feature.py"), ("A", "frontend/src/Page.tsx"), ("M", ".env.example")]) == []


def test_protected_zone_needs_the_owner_label():
    msgs = run([("M", "backend/app/auth.py"), ("M", ".github/workflows/tests.yml"), ("M", "AGENTS.md"), ("M", "scripts/guardrails.py")])
    assert len(msgs) == 4 and all("Zone protégée" in m for m in msgs)
    assert run([("M", "backend/app/auth.py")], labels=["core-change-approved"]) == []
    assert any("Zone protégée" in m for m in run([("M", ".env")]))


def test_deleting_or_moving_core_files_is_refused():
    assert any("supprimé ou déplacé" in m for m in run([("D", "backend/tests/test_api.py")]))
    assert any("supprimé ou déplacé" in m for m in run([("D", "frontend/src/App.tsx")]))
    assert run([("D", "README.md")]) == []                                          # hors base
    assert any("Fichier essentiel absent" in m for m in run([], tree=["backend/app/main.py"]))   # même sans diff : la base doit être là


def test_structure_rules_have_no_label_escape():
    for bad, why in [("newapp/server.py", "Nouveau dossier"), ("api/package.json", "Second projet Node"), ("services/requirements.txt", "Second environnement Python"),
                     ("Dockerfile.prod", "Second fichier de déploiement"), ("deploy/docker-compose.yml", "Second fichier de déploiement")]:
        msgs = run([("A", bad)], labels=["core-change-approved"], tree=TREE + [bad])
        assert any(why in m for m in msgs), (bad, msgs)
    second = TREE + ["backend/app/other_server.py"]
    msgs = run([("A", "backend/app/other_server.py")], tree=second, files={"backend/app/other_server.py": "app = FastAPI(title='x')"})
    assert any("Second serveur FastAPI" in m for m in msgs)
    router_ok = run([("A", "backend/app/api_new.py")], tree=TREE + ["backend/app/api_new.py"], files={"backend/app/api_new.py": "router = APIRouter()"})
    assert router_ok == []                                                          # un nouveau routeur est bienvenu


def test_secrets_are_refused():
    key = "sk-ant-" + "api03-" + "A" * 30
    assert any("Secret visible" in m for m in run([("M", "backend/app/agent.py")], files={"backend/app/agent.py": f"KEY = '{key}'"}))
    assert run([("M", "backend/app/agent.py")], files={"backend/app/agent.py": "KEY = os.environ['ANTHROPIC_API_KEY']"}) == []


def test_real_repository_passes_its_own_guard():
    tree = g._git("ls-files").splitlines()
    manifest = [l.strip() for l in g.MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    missing = [p for p in manifest if p not in set(tree)]
    assert manifest and not missing, missing
    msgs = g.check([], set(), tree, g._read, manifest)
    assert msgs == [], msgs
