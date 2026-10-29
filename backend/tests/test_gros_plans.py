"""Gros dossiers de plans (maison, immeuble, 40 pages et plus, exports AutoCAD / Revit / ArchiCAD) : chaque page est lue pour
elle-même (un niveau par page, étages de formes différentes), en haute définition (tuiles) avec les textes exacts du logiciel,
plusieurs pages à la fois ; au-delà du budget de temps, la lecture continue en arrière-plan. Le métré garde le niveau de chaque
pièce, compte un étage courant autant de fois que le plan le dit, calcule une pièce en L rectangle par rectangle et donne la
consigne de pose de chaque pièce. L'IA est simulée (pas de clé ici) : on vérifie tout ce que fait le code autour d'elle."""
import io
import json
import re
import threading
import time

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app import calc, pdfjob, plan_quote, plans
from app.database import SessionLocal
from app.main import app

A1 = (2384, 1684)


def _pdf(levels: list[str], text_pages: tuple[int, ...] = (), size=A1) -> bytes:
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=size)
    for k, niv in enumerate(levels, 1):
        c.setFont("Helvetica", 7)
        if k in text_pages:   # notice / CCTP : du texte suivi, pas un dessin
            for i in range(30):
                c.drawString(60, size[1] - 60 - i * 12, f"Article {i} : les travaux comprennent la fourniture et la mise en oeuvre.")
        else:
            c.drawString(100, size[1] - 80, f"{niv}  ECH 1/100")
            c.rect(100, 100, 600, 400)
            c.drawString(300, 300, "SEJOUR")
            c.drawString(300, 290, "S = 25,40 m²")
            c.rect(700, 100, 300, 400)
            c.drawString(800, 300, f"CHAMBRE {k}")
            c.drawString(800, 290, "12,00 m2")
        c.showPage()
    c.save()
    return b.getvalue()


def _fake(calls: list, pause: float = 0.0, broken: tuple[int, ...] = (), extra: dict | None = None):
    lock = threading.Lock()

    def call(content):
        text = content[-1]["text"]
        page = int(re.search(r"PAGE (\d+)", text).group(1))
        with lock:
            calls.append({"page": page, "images": sum(1 for x in content if x["type"] == "image"), "text": text})
        time.sleep(pause)
        if page in broken:
            return "je ne sais pas"
        niveau = re.search(r"\n[\d.]+;[\d.]+ (\S+)", text.split("TEXTES DE LA PAGE")[1]).group(1)
        return json.dumps({"type_page": "plan", "niveau": niveau, "repetition": 1, "unite_plan": "m", "pieces": [
            {"nom": "Séjour", "longueur_m": 6.35, "largeur_m": 4, "surface_m2": 25.4, "plafond": "oui", "raison": "FP BA13"},
            {"nom": f"Chambre {page}", "longueur_m": 4, "largeur_m": 3, "surface_m2": 12, "plafond": "oui", "raison": "FP BA13"}],
            **((extra or {}).get(page) or {})})
    return call


@pytest.fixture(autouse=True)
def _jobs_finis():
    yield
    for job in list(plans._JOBS.values()):   # une lecture en arrière-plan ne déborde jamais sur le test suivant
        job["thread"].join(120)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(plans.settings, "anthropic_api_key", "test")
    with TestClient(app) as c:
        yield c


def _upload(client, data: bytes, name="immeuble.pdf") -> str:
    return client.post("/api/files", files={"file": (name, data, "application/pdf")}).json()["id"]


def test_page_grand_format_en_tuiles_avec_les_textes_exacts(tmp_path):
    p = tmp_path / "a1.pdf"
    p.write_bytes(_pdf(["PLAN DU RDC"]))
    page = pdfjob.run("page", timeout=60, path=str(p), index=0)
    assert len(page["tiles"]) == 6                                       # A1 : 3 × 2 tuiles en haute définition
    assert all(0 <= t["box"][0] < t["box"][2] <= 1 for t in page["tiles"])
    words = {w["t"]: w for w in page["words"]}
    assert "S = 25,40 m²" in words and words["SEJOUR"]["y"] > 0.7 and words["SEJOUR"]["x"] < words["CHAMBRE 1"]["x"]
    small = tmp_path / "a4.pdf"
    small.write_bytes(_pdf(["PLAN"], size=(595, 842)))
    assert pdfjob.run("page", timeout=60, path=str(small), index=0)["tiles"] == []   # A4 : la page entière suffit


def test_immeuble_de_40_pages_lu_page_par_page_en_parallele_puis_en_arriere_plan(client, monkeypatch):
    levels = ["SOUS-SOL", "REZ-DE-CHAUSSEE"] + [f"R+{i}" for i in range(1, 39)]
    calls: list = []
    monkeypatch.setattr(plans, "_call", _fake(calls, pause=0.2))
    fid = _upload(client, _pdf(levels))
    with SessionLocal() as db:
        first = plans.analyze(db, fid, budget_s=4)
        db.commit()
        assert first["lecture"]["en_cours"] and first["lecture"]["pages_lues"] < 40         # rend la main, la lecture continue
        assert "arrière-plan" in first["lecture"]["note"]
        deadline = time.monotonic() + 240   # serveur de test chargé : large
        out = first
        while not out["lecture"]["complete"] and time.monotonic() < deadline:
            time.sleep(0.5)
            out = plans.analyze(db, fid, budget_s=5)
            db.commit()
    assert out["lecture"]["complete"] and out["lecture"]["pages_lues"] == 40
    assert len(calls) == 40 and len({c["page"] for c in calls}) == 40                       # chaque page lue UNE fois
    assert all(c["images"] == 7 for c in calls)                                              # vue d'ensemble + 6 tuiles
    assert all("CHAMBRE" in c["text"] and "AutoCAD" in c["text"] for c in calls)             # textes du logiciel + consigne
    assert [lv["niveau"] for lv in out["niveaux"]][:3] == ["SOUS-SOL", "REZ-DE-CHAUSSEE", "R+1"] and len(out["niveaux"]) == 40
    assert len(out["pieces"]) == 80 and out["total_plafond_confirme_m2"] == 40 * 37.4
    assert {r["niveau"] for r in out["pieces"] if r["nom"] == "Séjour"} == set(levels)        # le même nom à chaque étage
    with SessionLocal() as db:
        assert plans.analyze(db, fid) == out and len(calls) == 40                            # ensuite : cache, aucune relecture
        short = plans.compact(out, max_rooms=20)
        assert len(short["pieces"]) == 20 and short["pieces_non_listees"] == 60 and "TOUTES" in short["note_liste"]


def test_pages_de_texte_non_regardees_et_page_en_echec_relue_seule(client, monkeypatch):
    calls: list = []
    monkeypatch.setattr(plans, "_call", _fake(calls, broken=(3,)))
    fid = _upload(client, _pdf(["RDC", "NOTICE", "R+1", "R+2"], text_pages=(2,)))
    with SessionLocal() as db:
        out = plans.analyze(db, fid, budget_s=30)
        db.commit()
        assert sorted({c["page"] for c in calls}) == [1, 3, 4]                       # la notice (p. 2) n'est pas envoyée à l'IA
        assert out["lecture"]["non_lues"] == [3] and not out["lecture"]["complete"] and "redemande" in out["lecture"]["note"]
        assert "pages de texte non regardées : 2" in out["lecture"]["note"] and len(out["pieces"]) == 4
        d = plan_quote.build(out)
        assert any("Pages du plan non lues : 3" in m for m in d["missing"])          # le devis le dit, rien n'est caché
        monkeypatch.setattr(plans, "_call", _fake(calls))
        out = plans.analyze(db, fid, budget_s=30)
        db.commit()
    assert [c["page"] for c in calls].count(3) == 3 and [c["page"] for c in calls].count(1) == 1   # seule la page 3 est relue
    assert out["lecture"]["complete"] and len(out["pieces"]) == 6


def test_etage_courant_piece_en_l_et_pose_de_chaque_piece():
    analysis = {"pieces": [
        {"nom": "Séjour", "niveau": "RDC", "page": 1, "longueur_m": 6, "largeur_m": 4, "surface_m2": 24, "plafond": "oui"},
        {"nom": "Séjour", "niveau": "Étage courant", "page": 2, "longueur_m": 6, "largeur_m": 4, "surface_m2": 24, "plafond": "oui",
         "repetition": 4},
        {"nom": "Couloir", "niveau": "RDC", "page": 1, "surface_m2": 10, "plafond": "oui", "rectangles": [[5, 1.2], [3, 1.2]]}],
        "lecture": {"non_lues": []}}
    d = plan_quote.build(analysis)
    q = {x["sku"]: x["quantity"] for x in d["quantities"]}
    one = calc.ceiling_boards(6, 4)["plaques"]
    hall = calc.ceiling_boards(5, 1.2)["plaques"] + calc.ceiling_boards(3, 1.2)["plaques"]
    # séjour du RDC + 4 étages identiques + le couloir en L ; marge du patron une fois (24 + 96 + 10 = 130 m² → + 10)
    assert q["BA13-2000x1200"] == one * 5 + hall + 10
    assert d["inputs"]["surface_plafond_m2"] == 130
    assert {lv["niveau"]: lv["surface_m2"] for lv in d["niveaux"]} == {"RDC": 34, "Étage courant": 96}
    poses = {p["piece"]: p for p in d["pose"]}
    assert set(poses) == {"Séjour (RDC)", "Séjour (Étage courant)", "Couloir (RDC)"}
    assert poses["Couloir (RDC)"]["zones"] == 2 and poses["Séjour (Étage courant)"]["repetition"] == 4
    assert poses["Séjour (RDC)"]["plaques"].endswith(f"= {one}") and "lignes dans le sens des" in poses["Séjour (RDC)"]["fourrures"]
    only = plan_quote.build(analysis, rooms=["Séjour (RDC)"])                      # une pièce d'un étage précis
    assert [p["piece"] for p in only["pose"]] == ["Séjour (RDC)"]
    assert len(plan_quote.build(analysis, rooms=["Séjour"])["pose"]) == 2           # « Séjour » = à tous les étages


def test_le_metre_attend_la_fin_de_la_lecture(client, monkeypatch):
    from app.agent import AgentSession
    calls: list = []
    monkeypatch.setattr(plans, "_call", _fake(calls, pause=1.0))
    monkeypatch.setattr(plans, "BUDGET_S", 0.5)
    fid = _upload(client, _pdf([f"R+{i}" for i in range(12)]))
    with SessionLocal() as db:
        s = AgentSession(db, None, {"last_file_id": fid})
        out = s("read_plan", {})
        assert out["lecture"]["en_cours"]
        assert "en cours" in s("calculate_from_plan", {"include_to_confirm": True})["error"]   # jamais un métré à moitié
    plans._JOBS[fid]["thread"].join(60)                                                   # la lecture finit en arrière-plan
    assert len(plans._JOBS[fid]["resultats"]) == 12


def test_consignes_de_lecture_page_par_page():
    for w in ("UNE PAGE", "TUILES", "AutoCAD", "repetition", "rectangles", "niveau", "Couloir", "false ceiling", "sq.ft"):
        assert w in plans.PAGE_PROMPT
