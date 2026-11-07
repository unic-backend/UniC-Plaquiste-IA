"""Idées de plafond DESSINÉES pour le client : caisson, gorge lumineuse, bandeau, îlot. Vue de dessus cotée depuis les dimensions du
patron (rien d'inventé), longueurs de retombée et de ruban LED, plaques des retombées ; PNG partageable."""
import pytest
from fastapi.testclient import TestClient

from app import diagrams, plafond_design as pd
from app.main import app


@pytest.mark.parametrize("style, inner, ml, m2, led", [
    ("caisson", [3.8, 2.8], 13.2, 1.98, 13.2),   # marge 0,60 m : 5 − 1,2 × 4 − 1,2 ; retombée 15 cm
    ("gorge", [3.8, 2.8], 13.2, 1.98, 13.2),
    ("bandeau", [3.8, 2.8], 13.2, 1.98, 0.0),     # spots, pas de LED
    ("ilot", [2.5, 2.0], 9.0, 1.35, 9.0),         # îlot = moitié de la pièce
])
def test_geometrie_des_idees(style, inner, ml, m2, led):
    d = pd.design(style, 5, 4)
    assert d["interieur"] == inner and d["retombee_ml"] == ml and d["retombee_m2"] == m2 and d["led_ml"] == led
    assert d["plaques_retombees"] == 1
    svg = diagrams.sanitize(d["svg"])
    assert "5 m" in svg and f"{str(inner[0]).replace('.', ',').rstrip('0').rstrip(',')} ×" in svg


def test_petite_piece_marge_reduite_et_trop_etroite_refusee():
    assert pd.design("caisson", 3, 2)["interieur"] == [2.0, 1.0]       # marge ramenée à 0,50 m
    with pytest.raises(pd.DesignError):
        pd.design("gorge", 3, 1.4)
    with pytest.raises(pd.DesignError):
        pd.design("vitrail", 5, 4)


def test_trois_idees_par_defaut_et_ordre_des_cotes():
    ideas = pd.designs(4, 6)
    assert [d["style"] for d in ideas] == ["caisson", "gorge", "ilot"] and ideas[0]["piece"] == [6, 4]


def test_l_ia_dessine_les_idees_pour_le_client():
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("ceiling_designs", {"length_m": 5, "width_m": 4})
        assert [i["nom"] for i in out["idees"]] == ["Caisson central", "Gorge lumineuse", "Îlot suspendu"]
        assert len(s.images) == 3 and all(img["filename"].endswith(".png") for img in s.images)
        assert "svg" not in out["idees"][0]                               # le dessin part en image, pas dans le texte
        assert "error" in s("ceiling_designs", {"length_m": 3, "width_m": 1.2})


@pytest.mark.parametrize("piece, L, W, first, why", [
    ("salon", 5, 4, ["caisson", "ilot", "gorge"], "pièce à vivre"),
    ("la chambre des parents", 4, 3.5, ["gorge", "caisson", "bandeau"], "repos"),
    ("cuisine", 4, 3, ["bandeau", "ilot"], "plan de travail"),
    ("salle à manger", 5, 4, ["ilot", "caisson", "gorge"], "table"),
    ("salle de bain", 3, 2.5, ["bandeau"], "hydrofuges"),
    ("couloir", 6, 1.8, ["bandeau", "gorge"], "passage"),
    ("", 9, 3, ["bandeau", "gorge", "caisson"], "pièce longue"),   # pas de pièce nommée : la forme décide
    ("", 5, 4, ["caisson", "gorge", "ilot"], ""),
])
def test_idees_adaptees_a_la_piece(piece, L, W, first, why):
    styles, reason = pd.suggest(piece, L, W)
    assert list(styles) == first and why in reason
    assert [d["style"] for d in pd.designs(L, W, piece=piece)] == first


def test_le_choix_du_patron_passe_avant_le_conseil():
    assert [d["style"] for d in pd.designs(5, 4, ["gorge"], piece="cuisine")] == ["gorge"]
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("ceiling_designs", {"length_m": 4, "width_m": 3.5, "piece": "chambre"})
        assert [i["style"] for i in out["idees"]] == ["gorge", "caisson", "bandeau"] and "repos" in out["conseil"]
        out = s("ceiling_designs", {"length_m": 4, "width_m": 3.5, "piece": "chambre", "styles": ["ilot"]})
        assert [i["style"] for i in out["idees"]] == ["ilot"] and "conseil" not in out


def test_tracage_et_decoupe_du_caisson():
    """Comment tracer et couper : distances aux murs, diagonales d'équerre, faces courtes moins 2 épaisseurs, bandes dans les plaques."""
    t = pd.trace_decoupe("caisson", 5, 4)
    assert t["distances_murs_m"] == [0.6, 0.6] and t["diagonale_m"] == 4.72          # √(3,8² + 2,8²)
    faces = {f["face"]: f for f in t["bandes"]["faces"]}
    assert faces["A"]["longueur_cm"] == 380 and faces["B"]["longueur_cm"] == 277.5    # 280 − 2 × 1,25
    assert faces["A"]["morceaux_cm"] == [200, 180]
    cut = t["bandes"]
    assert cut["bandes_par_plaque"] == 8 and cut["bandes"] == 7 and cut["plaques"] == 1  # les deux 77,5 dans une seule bande
    used = sum(p["cm"] for b in cut["plan_bandes"] for p in b)
    assert used == pytest.approx(2 * 380 + 2 * 277.5) and cut["chute_cm"] == pytest.approx(7 * 200 - used)
    assert any("4,72 m" in s for s in t["tracage"]) and "<svg" in diagrams.sanitize(t["svg"])


def test_retombee_haute_moins_de_bandes_par_plaque():
    """Retombée de 25 cm : 4 bandes par plaque (pas 4,8) — le compte à la surface en oubliait."""
    t = pd.trace_decoupe("ilot", 6, 4.5, retombee_m=0.25)
    assert t["distances_murs_m"] == [1.5, 1.12] and t["bandes"]["bandes_par_plaque"] == 4
    assert t["plaques_retombees"] == pd.design("ilot", 6, 4.5, retombee_m=0.25)["plaques_retombees"] == 2
    with pytest.raises(pd.DesignError):
        pd.trace_decoupe("caisson", 5, 4, retombee_m=1.3)


def test_outil_plan_de_pose_decor(monkeypatch):
    from app import diagrams as dg
    from app.agent import AgentSession
    from app.database import SessionLocal
    monkeypatch.setattr(dg, "render", lambda db, title, svg, uid: type("A", (), {"id": "x", "filename": "t.png"})())
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s._t_pose_plan(5, 4, ouvrage="decor", decor_style="gorge")
        assert out["plaques_retombees"] == 1 and out["tracage"] and s.images[0]["title"].startswith("Traçage et découpe")
        assert "error" in s._t_pose_plan(5, 4, ouvrage="decor")
