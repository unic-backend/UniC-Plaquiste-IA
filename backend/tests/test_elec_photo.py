"""Électricité et climatisation (repères NF C 15-100 sourcés, calculs en code) et réponse EN PHOTO (repères dessinés sur l'image)."""
import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import annotate, elec, plans
from app.config import settings
from app.main import app


@pytest.fixture
def c(monkeypatch):
    monkeypatch.setattr(settings, "unic_access_code", "")
    with TestClient(app) as client:
        yield client


def test_cable_trop_fin_pour_le_disjoncteur_est_un_danger():
    out = elec.controle_circuit("prises_12", 1.5, 20, points=14)
    graves = [x["gravite"] for x in out["constats"]]
    assert not out["conforme"] and graves.count("danger") == 2 and "defaut" in graves   # 1,5 mm² > 16 A ; section mini 2,5 ; 14 > 12 prises
    ok = elec.controle_circuit("eclairage", 1.5, 16, points=8)
    assert ok["conforme"] and ok["constats"][0]["gravite"] == "ok" and "Tableau-section" in ok["source"]
    with pytest.raises(elec.ElecError):
        elec.controle_circuit("four a pain", 2.5, 20)


def test_chute_de_tension_et_section():
    d = elec.chute_tension(20, 15, 2.5)                        # exemple de la source : 2 × 0,0225 × 15 × 20 / 2,5 = 5,4 V
    assert d["volts"] == 5.4 and d["pourcent"] == 2.35
    s = elec.section_pour(elec.courant(3000), 30)              # 13,04 A sur 30 m : 1,5 mm² = 5,1 % > 5 % → 2,5 mm²
    assert s["section_mm2"] == 2.5 and s["disjoncteur_a"] == 16 and s["chute"]["pourcent"] <= 5
    assert elec.section_pour(13, 30, "eclairage")["section_mm2"] == 4.0   # éclairage : 3 % au plus
    with pytest.raises(elec.ElecError):
        elec.section_pour(60)                                  # au-delà du tableau des logements


def test_clim_puissance_et_ligne_dediee():
    p = elec.clim_puissance(20)                                # 20 m² × 100 W = 2 000 W ≈ 6 824 BTU/h → 7 000
    assert p["puissance_froid_w"] == 2000 and p["taille_conseillee_btu"] == 7000
    assert elec.clim_puissance(20, forte_chaleur=True)["taille_conseillee_btu"] == 9000   # 2 500 W ≈ 8 530 BTU/h
    assert elec.clim_puissance(80)["taille_conseillee_btu"] is None                        # au-delà des splits courants
    a = elec.clim_alimentation(11)
    assert a["section_mm2"] == 1.5 and a["disjoncteur_a"] == 16 and any("multiprise" in r for r in a["pose"])
    r = elec.regles()
    assert "vert-jaune" in " ".join(r["couleurs"]).lower() and "30 mA" in " ".join(r["differentiels"]) and r["sources"]


def test_outil_ia_elec_calc(c):
    from app.agent import AgentSession
    from app.database import SessionLocal
    with SessionLocal() as db:
        s = AgentSession(db, None, {})
        assert s("elec_calc", {"action": "circuit", "usage": "plaque_mono", "section_mm2": 2.5, "disjoncteur_a": 32})["conforme"] is False
        assert s("elec_calc", {"action": "section", "puissance_w": 2000, "longueur_m": 10})["section_mm2"] == 1.5
        out = s("elec_calc", {"action": "clim", "surface_m2": 16, "courant_a": 6})
        assert out["taille_conseillee_btu"] == 7000 and out["alimentation"]["disjoncteur_a"] == 10
        assert "error" in s("elec_calc", {"action": "section"})


def _png(w=800, h=600) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (90, 90, 90)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_reperes_nettoyes_et_dessines():
    marks = annotate.clean([{"zone": [0.6, 0.1, 0.2, 0.4], "titre": "Phase en bleu", "gravite": "danger"},
                            {"zone": [0.5, 0.5, 0.5, 0.9]},                       # zone vide : écartée
                            {"zone": [-1, 0.2, 0.3, 2], "titre": "Terre", "gravite": "inconnue"},
                            "pas un repère"])
    assert [m["n"] for m in marks] == [1, 2] and marks[0]["zone"] == [0.2, 0.1, 0.6, 0.4]
    assert marks[1]["zone"] == [0.0, 0.2, 0.3, 1.0] and marks[1]["gravite"] == "info"
    png = annotate.draw(_png(), marks, "Erreurs du coffret")
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width >= 1100 and img.height > img.width * 600 / 800   # agrandie + légende en bas
    assert img.getpixel((round(0.2 * img.width) + 2, round(0.25 * 0.75 * img.width))) != (90, 90, 90)  # cadre dessiné


def test_reponse_en_photo_sur_un_coffret(c, monkeypatch):
    from app.agent import AgentSession
    from app.database import SessionLocal
    monkeypatch.setattr(plans.settings, "anthropic_api_key", "test")
    calls = []
    answer = ("1. Disjoncteur 32 A sur câble 1,5 mm² (estimé) : danger.\n2. Terre non raccordée : défaut.\n"
              "REPERES\n" + json.dumps({"reperes": [{"n": 1, "page": 1, "zone": [0.1, 0.1, 0.3, 0.4], "titre": "32 A sur 1,5 mm²",
                                                    "gravite": "danger"},
                                                   {"n": 2, "zone": [0.5, 0.6, 0.7, 0.9], "titre": "Terre libre", "gravite": "defaut"}]}))
    monkeypatch.setattr(plans, "_call", lambda content: calls.append(content) or answer)
    buf = io.BytesIO()
    Image.new("RGB", (900, 700), "white").save(buf, format="PNG")
    fid = c.post("/api/files", files={"file": ("coffret.png", buf.getvalue(), "image/png")}).json()["id"]
    with SessionLocal() as db:
        s = AgentSession(db, None, {"last_file_id": fid})
        out = s("read_plan", {"question": "Le technicien a-t-il bien câblé ?", "domaine": "electricite", "annoter": True})
        assert out["photo_annotee"] and [m["titre"] for m in out["reperes"]] == ["32 A sur 1,5 mm²", "Terre libre"]
        assert "REPERES" not in out["reponse"] and "Terre non raccordée" in out["reponse"]
        assert s.images and s.images[-1]["title"] == "Réponse en photo"
    prompt = calls[0][-1]["text"]
    assert "électricien expert" in prompt and "1,5 mm² → 16 A" in prompt and "couper le disjoncteur général" in prompt
    assert '"reperes"' in prompt


def test_sans_reperes_la_reponse_reste_en_texte(c, monkeypatch):
    monkeypatch.setattr(plans.settings, "anthropic_api_key", "test")
    monkeypatch.setattr(plans, "_call", lambda content: "1. Split bien posé, évacuation en pente.")
    buf = io.BytesIO()
    Image.new("RGB", (600, 400), "white").save(buf, format="PNG")
    fid = c.post("/api/files", files={"file": ("clim.png", buf.getvalue(), "image/png")}).json()["id"]
    from app.database import SessionLocal
    with SessionLocal() as db:
        out = plans.ask(db, fid, "La clim est bien posée ?", domaine="climatisation", annoter=True)
    assert out["photo_annotee"] is None and "texte seulement" in out["note_photo"] and "Split" in out["reponse"]
