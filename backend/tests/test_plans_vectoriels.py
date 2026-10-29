"""Plans vectoriels (exports de logiciels) : les cloisons sont des traits de couleur décrits dans la légende, les pièces portent
une étiquette (code / nom / cotes / surface), le cartouche donne le niveau, les niveaux concernés, la hauteur et l'échelle.
Tout cela est MESURÉ dans le fichier par le code, au point près, sans IA. Référence : le dossier d'essai du patron « Tour
Horizon R+40 » (6 planches + un corrigé), dont le corrigé donne le métré exact des cloisons et les surfaces."""
import io
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from app import pdfjob, plan_quote, plans

TOUR = Path(__file__).parent / "fixtures" / "tour_horizon_r40.pdf"
STD, HYDRO, DOUBLE = ("Cloison 72/48 - 1 BA13 std chaque face", "Cloison 72/48 - BA13 hydro H1 (pièces humides)",
                      "Cloison 98/48 - 2 BA13 chaque face + laine 45 mm")
# corrigé du patron : linéaire par niveau (ml) et cartouche (niveaux concernés, hauteur)
CORRIGE = {2: ("RDC", 1, 4.0, {STD: 33.0, HYDRO: 47.0, DOUBLE: 44.0}),
           3: ("R+1 et R+2", 2, 3.5, {STD: 4.0, HYDRO: 59.5, DOUBLE: 29.5}),
           4: ("R+3 à R+35", 33, 2.8, {STD: 17.5, HYDRO: 117.0, DOUBLE: 42.5}),
           5: ("R+36 à R+39", 4, 2.8, {STD: 31.75, HYDRO: 104.5, DOUBLE: 30.25}),
           6: ("R+40", 1, 3.2, {STD: 12.75, HYDRO: 60.5, DOUBLE: 39.75})}
PIECES = {2: (20, 520.5), 3: (17, 686.99), 4: (40, 687.0), 5: (41, 687.0), 6: (24, 687.0)}   # pièces étiquetées, m²


@pytest.fixture(scope="module")
def mesures() -> dict[int, dict]:
    return {n: pdfjob.run("page", timeout=60, path=str(TOUR), index=n - 1)["mesures"] for n in range(1, 13)}


@pytest.mark.parametrize("n", sorted(CORRIGE))
def test_cloisons_cartouche_et_pieces_mesures_comme_le_corrige(mesures, n):
    niveau, niveaux, hauteur, ml = CORRIGE[n]
    m = mesures[n]
    assert m["cartouche"] == {"niveau": niveau, "niveaux": niveaux, "hauteur_m": hauteur, "echelle": "1/125"}
    assert {c["libelle"]: c["longueur_m"] for c in m["cloisons"]} == ml          # au centimètre près
    assert m["echelle"]["source"] == "échelle écrite"
    count, surface = PIECES[n]
    rooms = m["pieces"]
    assert len(rooms) == count and len({r["code"] for r in rooms}) == count
    assert all(abs(r["longueur_m"] * r["largeur_m"] - r["surface_m2"]) <= 0.01 for r in rooms)   # chaque étiquette bien lue
    assert round(sum(r["surface_m2"] for r in rooms), 2) == surface


def test_le_corrige_et_la_couverture_ne_sont_pas_mesures(mesures):
    assert not mesures[1].get("cloisons") and not mesures[1].get("pieces")
    assert all(not mesures[n] for n in range(7, 13))                             # tableaux : pas un dessin


def _lecture(mesures: dict[int, dict]) -> dict:
    """Ce que l'IA rend (simulé) : rôle de chaque page ; le corrigé lu comme un tableau ; un palier sans cote."""
    roles = {1: "programme", 2: "plan_niveau", 3: "plan_niveau", 4: "plan_type", 5: "plan_type", 6: "plan_niveau"}
    results = {}
    for n in range(1, 13):
        data = {"type_page": "plan" if 2 <= n <= 6 else "autre", "role_page": roles.get(n, "tableau"), "pieces": []}
        if n >= 7:
            data["pieces"] = [{"nom": "Séjour", "logement": "A", "longueur_m": 7.5, "largeur_m": 8, "surface_m2": 60}]
        if n == 4:
            data["pieces"] = [{"nom": "Palier / circulation", "plafond": "a_confirmer"},
                              {"nom": "SDB 2", "code": "A.13", "plafond": "a_confirmer", "raison": "pièce humide"},
                              {"nom": "Bureau", "longueur_m": 4, "largeur_m": 4, "surface_m2": 16, "plafond": "oui"}]   # inventée
        if mesures[n]:
            data["_mesures"] = mesures[n]
        results[n] = data
    return plans._merge(results, list(results), {}, False, [], [])


def test_metre_des_cloisons_de_la_tour_egal_au_corrige(mesures):
    out = _lecture(mesures)
    mc = out["metre_cloisons"]
    assert {t["libelle"]: (t["ml"], t["m2"]) for t in mc["total"]} == {
        STD: (758.25, 2173.4), HYDRO: (4505.5, 12779.3), DOUBLE: (1666.25, 4775.5)}   # récapitulatif tour (41 niveaux)
    assert (mc["total_ml"], mc["total_m2"]) == (6930.0, 19728.2)
    etage = next(r for r in mc["par_niveau"] if r["niveau"] == "R+3 à R+35")
    assert etage["niveaux"] == 33 and etage["hauteur_m"] == 2.8
    assert {t["libelle"]: t["m2"] for t in etage["types"]} == {STD: 1617.0, HYDRO: 10810.8, DOUBLE: 3927.0}


def test_zones_de_plafond_par_niveau_sans_doublon(mesures):
    out = _lecture(mesures)
    rooms = [r for r in out["pieces"] if r.get("source") == "dessin"]
    assert len(rooms) == 142
    by = {}
    for r in rooms:
        by[r["niveau"]] = round(by.get(r["niveau"], 0) + r["surface_m2"] * r["repetition"], 2)
    assert by == {"RDC": 520.5, "R+1 et R+2": 1373.98, "R+3 à R+35": 22671.0, "R+36 à R+39": 2748.0, "R+40": 687.0}
    sdb = next(r for r in rooms if r.get("code") == "A.13" and r["niveau"] == "R+3 à R+35")
    assert sdb["raison"] == "pièce humide" and sdb["longueur_m"] == 3.0          # cotes du dessin, compréhension de l'IA
    assert any("Palier" in r["nom"] for r in out["pieces"])                       # zone sans étiquette gardée (sans surface)
    assert not any(r["nom"] == "Bureau" and r["niveau"] == "R+3 à R+35" for r in out["pieces"])
    assert any("sans étiquette sur le dessin" in x for x in out["remarques"])
    assert any("récapitulatif des plans" in x for x in out["remarques"])         # le corrigé n'est pas recompté
    d = plan_quote.build(out, include_to_confirm=True)
    assert d["inputs"]["surface_plafond_m2"] == round(sum(by.values()), 2)
    assert any(p["piece"].startswith("Séjour") and p["repetition"] == 33 for p in d["pose"])


def _pdf(legend: bool = True, scale: bool = True) -> bytes:
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=(1191, 842))
    c.setFont("Helvetica", 6)
    c.setStrokeColorRGB(0.9, 0.45, 0.08)
    c.setLineWidth(1.6)
    c.line(100, 400, 100 + 4 / 0.0441, 400)                      # 4 m de cloison à 1/125
    c.line(300, 300, 300, 300 + 2 / 0.0441)                      # 2 m
    c.line(300, 300, 300, 300 + 1 / 0.0441)                      # recouvrement : pas compté deux fois
    c.line(60, 200, 90, 200)                                     # trait du plan voisin d'une étiquette de pièce
    c.drawString(95, 198, "Cloison du hall")
    if legend:
        c.line(900, 600, 935, 600)
        c.drawString(945, 598, "Cloison 72/48 - 1 BA13")
        c.setStrokeColorRGB(0.1, 0.1, 0.1)
        c.line(900, 580, 935, 580)
        c.drawString(945, 578, "Voile béton")
    if scale:
        c.drawString(900, 700, "Échelle")
        c.drawString(1050, 700, "1/125")
    c.save()
    return b.getvalue()


def test_legende_echelle_et_recouvrements(tmp_path):
    p = tmp_path / "plan.pdf"
    p.write_bytes(_pdf())
    m = pdfjob.run("page", timeout=60, path=str(p), index=0)["mesures"]
    assert [(c["libelle"], round(c["longueur_m"], 1)) for c in m["cloisons"]] == [("Cloison 72/48 - 1 BA13", 7.3)]   # 4 + 2 + 1,32
    p.write_bytes(_pdf(scale=False))
    m = pdfjob.run("page", timeout=60, path=str(p), index=0)["mesures"]
    assert "cloisons" not in m and m["echelle"]["m_par_point"] is None           # sans échelle : rien de mesuré, rien d'inventé
    p.write_bytes(_pdf(legend=False))
    assert "cloisons" not in pdfjob.run("page", timeout=60, path=str(p), index=0)["mesures"]   # sans légende : idem


# ---------- matériaux des cloisons mesurées ----------

def test_systeme_lu_dans_la_legende():
    assert plan_quote.systeme(STD) == {"couches": 1, "ossature_mm": 48, "hydro": False, "laine_mm": 0, "faces": 2}
    assert plan_quote.systeme(HYDRO)["hydro"] is True
    assert plan_quote.systeme(DOUBLE) == {"couches": 2, "ossature_mm": 48, "hydro": False, "laine_mm": 45, "faces": 2}
    assert plan_quote.systeme("Cloison 120/70 - BA13 + isolant")["ossature_mm"] == 70
    assert plan_quote.systeme("Cloison 120/70 - BA13 + isolant")["laine_mm"] is None          # isolant sans épaisseur écrite
    assert plan_quote.systeme("Doublage 1 BA13 sur rails")["faces"] == 1


def test_materiaux_des_cloisons_mur_par_mur(mesures):
    from app import calc
    out = _lecture(mesures)
    types = {t["libelle"]: t for t in plan_quote.cloisons_mesurees(out["metre_cloisons"])}
    assert {k: (t["ml"], t["m2"]) for k, t in types.items()} == {
        STD: (758.25, 2173.4), HYDRO: (4505.5, 12779.3), DOUBLE: (1666.25, 4775.5)}   # mêmes nombres que le corrigé
    assert {k: t["murs"] for k, t in types.items()} == {STD: 247, HYDRO: 1293, DOUBLE: 386}   # tronçons × niveaux
    for label, t in types.items():
        q = {x.sku: x for x in t["result"].quantities}
        walls = [(r, lv["hauteur_m"]) for lv in out["metre_cloisons"]["par_niveau"] for ty in lv["types"] if ty["libelle"] == label
                 for r in ty["troncons_m"] for _ in range(lv["niveaux"])]
        # montants : règle du patron recomptée mur par mur (60 cm, jonctions doublées, rallonges au-dessus de 2,80 m)
        assert q["MONTANT-M48"].quantity == sum(calc.stud_bars(calc.studs_needed(a, 0.6, 1.2, 2.0), h) for a, h in walls)
        layers = t["systeme"]["couches"]
        board = next(x for x in t["result"].quantities if x.sku.startswith("BA13-"))
        assert board.quantity >= calc.ceil_int(2 * layers * t["m2"] / 2.4)            # jamais moins que la surface à couvrir
        assert q["UC-RAILS-48-MM"].quantity >= calc.ceil_int(2 * t["ml"] / 2.8)
    assert next(x for x in types[HYDRO]["result"].quantities if x.sku.startswith("BA13-")).sku == "BA13-2000x1200-H"
    laine = {x.sku: x for x in types[DOUBLE]["result"].quantities}["UC-LAINE-DE-VERRE-PAQUET"]
    assert laine.quantity == 354 and laine.status == calc.STATUS_ASSUMED and "45 mm" in laine.name   # 4 775,5 m² / 13,5
    assert "UC-LAINE-DE-VERRE-PAQUET" not in {x.sku for x in types[STD]["result"].quantities}


def test_devis_cloisons_seules_ou_avec_plafonds(mesures):
    out = _lecture(mesures)
    only = plan_quote.build(out, cloisons_du_plan=True, plafonds=False)
    q = {x["sku"]: x["quantity"] for x in only["quantities"]}
    assert "UC-TIGES-A-L-UNITE" not in q and "BA13-2000x1200-H" in q and "UC-LAINE-DE-VERRE-PAQUET" in q
    assert sum(1 for s in only["steps"] if s["label"].startswith("Cloisons mesurées")) == 3
    both = plan_quote.build(out, include_to_confirm=True, cloisons_du_plan=True)
    qb = {x["sku"]: x["quantity"] for x in both["quantities"]}
    assert qb["UC-TIGES-A-L-UNITE"] > 0 and qb["MONTANT-M48"] == q["MONTANT-M48"]
    with pytest.raises(plan_quote.PlanQuoteError, match="Aucune cloison mesurée"):
        plan_quote.build({"pieces": [{"nom": "Salon", "surface_m2": 20, "plafond": "oui"}]}, cloisons_du_plan=True)
