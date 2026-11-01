"""Anti-vibecode : les 43 signes d'un site « fait par l'IA » sont donnés à Claude Code pour les projets web de UniC Code.
Deux copies des règles (le skill du dépôt dans docs/anti-vibecode, le module du serveur) : elles doivent rester identiques."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import anti_vibecode  # noqa: E402
from app.main import app  # noqa: E402

SKILL = Path(__file__).resolve().parents[2] / "docs" / "anti-vibecode"


def _rows():
    md = (SKILL / "references" / "signs.md").read_text(encoding="utf-8")
    out = []
    for line in md.splitlines():
        m = re.match(r"\|\s*(\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", line)
        if m:
            out.append((int(m[1]), m[2], m[4]))
    return out


def test_le_module_du_serveur_reprend_mot_pour_mot_le_skill_du_depot():
    assert _rows() == list(anti_vibecode.SIGNS)
    assert [n for n, _, _ in anti_vibecode.SIGNS] == list(range(1, 44))


def test_le_skill_est_complet_dans_le_depot():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert re.search(r"^name:\s*anti-vibecode\s*$", head, re.M) and "description:" in head
    assert "references/signs.md" in text and "scripts/scan.mjs" in text and (SKILL / "scripts" / "scan.mjs").is_file()
    assert "frontend/" in text   # le design de l'appli UniC elle-même n'est pas réécrit


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent")
def test_le_scanner_trouve_les_signes_d_un_site_vibecode_et_laisse_un_site_propre(tmp_path):
    scan = SKILL / "scripts" / "scan.mjs"
    mauvais, propre = tmp_path / "mauvais", tmp_path / "propre"
    mauvais.mkdir()
    propre.mkdir()
    (mauvais / "index.html").write_text(
        "<title>Create Next App</title><button class='bg-indigo-600'>Go</button><Sparkles/><p>Boost your business</p>", encoding="utf-8")
    (propre / "index.html").write_text(
        "<title>Boulangerie Diop, Dakar</title><meta property='og:image' content='/og.png'>"
        "<a href='/mentions-legales'>Mentions légales</a><a href='/confidentialite'>Confidentialité</a>", encoding="utf-8")

    def lancer(dossier):
        out = subprocess.run(["node", str(scan), str(dossier), "--json"], capture_output=True, text=True, timeout=60, check=True).stdout
        return {int(n) for n in json.loads(out)["found"]}
    assert {5, 17, 29, 39, 37, 38, 41} <= lancer(mauvais)
    assert lancer(propre) == set()


def test_seuls_les_projets_web_recoivent_les_regles():
    assert anti_vibecode.wanted("Un site vitrine pour une boulangerie à Dakar")
    assert anti_vibecode.wanted("Une landing page pour mon entreprise")
    assert anti_vibecode.wanted("Fais un tableau de bord en HTML")
    assert anti_vibecode.wanted("Ajoute un bouton", "Un site de réservation")   # suite d'un projet web
    for texte in ("Un jeu de memory pour enfants", "Un script qui trie mes factures", "Fais-le vite", "Un document Word pour un devis"):
        assert not anti_vibecode.wanted(texte), texte


def test_le_bloc_envoye_a_claude_code_porte_les_43_signes_et_reste_petit():
    bloc = anti_vibecode.block()
    assert bloc.count("\n") == 43 and "01. Purple gradient" in bloc and "43. Pages that take forever" in bloc
    assert "faux témoignage" in bloc and "TODO" in bloc and "la demande l'emporte" in bloc
    assert len(bloc) < 6000


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


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


class _R:
    status_code, content = 204, b""

    def json(self):
        return {}


def _inputs(monkeypatch):
    from app import repair
    seen = []

    def gh(method, path, token, **kw):
        if path.endswith("/dispatches"):
            seen.append(kw["json"]["inputs"])
        return _R()
    monkeypatch.setattr(repair, "_gh", gh)
    return seen


def test_un_site_part_avec_les_regles_et_sa_demande_intacte(client, db, monkeypatch):
    seen = _inputs(monkeypatch)
    demande = "Un site vitrine pour une boulangerie à Dakar. " + "Détail. " * 900   # demande très longue : jamais coupée par les règles
    assert client.post("/api/code/projects", json={"request": demande[:8000]}).status_code == 200
    (inputs,) = seen
    assert inputs["request"].startswith(demande[:200]) and inputs["request"].endswith(anti_vibecode.block())
    assert len(inputs["request"]) <= 20_000


def test_un_jeu_ou_un_script_part_sans_les_regles(client, db, monkeypatch):
    seen = _inputs(monkeypatch)
    for demande in ("Un jeu de memory pour enfants", "Un script qui classe mes factures par mois"):
        assert client.post("/api/code/projects", json={"request": demande}).status_code == 200
    assert len(seen) == 2 and all("DESIGN :" not in i["request"] for i in seen)
