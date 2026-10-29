"""Le client choisit une idée de plafond dessinée (caisson, gorge, bandeau, îlot) : elle devient des quantités de devis — plaques des
retombées (règle des plaques du moteur) et ruban LED en ml. L'ossature des retombées et le prix du LED sont signalés à donner, jamais
inventés ; une retombée dite n'est pas prise pour le plénum."""
import pytest
from fastapi.testclient import TestClient

from app import calc
from app.main import app


def _decor(r):
    return {q.name: q.quantity for q in r.quantities if "retombées" in q.name or "LED" in q.name}


@pytest.mark.parametrize("text, style, boards, led", [
    ("faux plafond 5x4 avec gorge lumineuse", "gorge", 1, 14),                 # 13,2 ml × 0,15 m = 1,98 m² → 1 plaque ; LED ⌈13,2⌉
    ("faux plafond 5x4 avec caisson central retombée de 20 cm", "caisson", 2, None),   # 13,2 × 0,20 = 2,64 m² → 2 plaques ; pas de LED
    ("faux plafond 5x4 avec caisson et led", "caisson", 1, 14),
    ("faux plafond 5 x 4 îlot", "ilot", 1, 9),
    ("faux plafond 5x4 bandeau avec spots", "bandeau", 1, None),
])
def test_l_idee_choisie_devient_des_quantites(text, style, boards, led):
    r = calc.calculate_from_text(text)
    d = _decor(r)
    assert r.inputs["decor"]["style"] == style
    assert next(v for k, v in d.items() if "retombées" in k) == boards
    assert d.get("Ruban LED (ml)") == led
    assert any("Ossature des retombées" in m for m in r.missing)
    assert ("Ruban LED : prix" in " ".join(r.missing)) == bool(led)
    assert r.to_dict()["verification"]["ok"]


def test_retombee_n_est_pas_le_plenum():
    r = calc.calculate_from_text("faux plafond 5x4 avec caisson retombée de 20 cm")
    assert "plenum_m" not in r.inputs and r.inputs["decor"]["retombee_m"] == 0.2
    assert calc.calculate_from_text("faux plafond 5x4 plénum 40 cm avec caisson").inputs["plenum_m"] == 0.4


def test_sans_decor_rien_n_est_ajoute_et_plusieurs_pieces_demandent_laquelle():
    assert "decor" not in calc.calculate_from_text("faux plafond 5x4").inputs
    r = calc.calculate_from_text("faux plafond salon 5x4 et chambre 4x3 avec gorge")
    assert "decor" not in r.inputs and any("dans quelle pièce" in m for m in r.missing)


def test_l_ia_passe_du_dessin_au_devis():
    from app.agent import AgentSession
    from app.database import SessionLocal
    with TestClient(app), SessionLocal() as db:
        s = AgentSession(db, None, {})
        out = s("calculate_materials", {"kind": "ceiling", "length_m": 5, "width_m": 4, "decor_style": "gorge"})
        names = [q["name"] for q in out["quantites"]]
        assert any("retombées" in n for n in names) and "Ruban LED (ml)" in names and out["verification"]["ok"]
        assert "error" in s("calculate_materials", {"kind": "ceiling", "length_m": 3, "width_m": 1.2, "decor_style": "gorge"})
