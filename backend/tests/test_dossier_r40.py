"""Dossier d'essai du patron « Tour de grand standing R+40 » (11 pages) : couverture, programme (niveaux → logements), plan du
RDC, plan d'étage courant (R+2 à R+35), fiches des logements types A, B, C, D, carnet de cloisons, tableaux de surfaces,
scénarios de test. Les pages sont simulées telles que l'IA les lit (une page à la fois) ; on vérifie ce que le CODE en fait,
avec les réponses attendues écrites dans le dossier (page 11) :
- 136 logements courants + 8 premium = 144 ; 68 Type A, 68 Type B, 7 Type C, 1 Type D ;
- surfaces intérieures 157 / 117 / 204 / 248 m² (balcons exclus) retrouvées par la somme des pièces ;
- un type décrit sur sa fiche ET dans un tableau n'est compté qu'UNE fois ;
- cloisons : pas de cotes ni d'échelle → aucun métré inventé."""
from app import plan_quote, plans


def _rooms(typ: str | None, rows: list[tuple], plafond: str = "a_confirmer") -> list[dict]:
    return [{"nom": n, "logement": typ, "surface_m2": s, "plafond": plafond, "raison": ""} for n, s in rows]


A = [("Séjour / salle à manger", 45), ("Cuisine", 16), ("Suite parentale", 22), ("Dressing", 7), ("SDB parentale", 8),
     ("Chambre 2", 15), ("Chambre 3", 15), ("SDB commune", 6), ("WC invités", 2), ("Buanderie", 5), ("Entrée / dégagement", 16)]
B = [("Séjour / salle à manger", 36), ("Cuisine", 13), ("Chambre parentale", 19), ("Dressing", 5), ("SDB principale", 7),
     ("Chambre 2", 14), ("SDB 2", 5), ("WC invités", 2), ("Buanderie", 4), ("Entrée / dégagement", 12)]
C = [("Séjour / salle à manger", 52), ("Cuisine", 18), ("Suite parentale", 24), ("Dressing suite", 8), ("SDB parentale", 10),
     ("Chambre 2", 16), ("Chambre 3", 16), ("Chambre 4", 15), ("SDB commune", 7), ("Salle d'eau secondaire", 6),
     ("WC invités", 2), ("Buanderie", 6), ("Cellier", 4), ("Entrée / dégagement", 20)]
D = [("Grand séjour / salle à manger", 65), ("Cuisine", 20), ("Suite parentale", 26), ("Dressing suite", 10), ("SDB parentale", 12),
     ("Chambre 2", 18), ("Chambre 3", 17), ("Chambre 4", 16), ("SDB commune", 8), ("Salle d'eau secondaire", 6),
     ("WC invités", 2), ("Buanderie", 6), ("Bureau", 12), ("Cellier", 5), ("Entrée / dégagement", 25)]

PAGES = {
    1: {"type_page": "autre", "role_page": "autre", "pieces": []},
    2: {"type_page": "autre", "role_page": "programme", "pieces": [],
        "logements": [{"type": "Type A", "description": "3 chambres", "nombre_total": 68},
                      {"type": "Type B", "description": "2 chambres", "nombre_total": 68},
                      {"type": "Type C", "description": "4 chambres", "nombre_total": 7},
                      {"type": "Type D", "description": "penthouse 4 chambres", "nombre_total": 1}],
        "programme": [{"niveaux": "SS3", "nombre_niveaux": 1, "affectation": "Stationnement / technique", "logements": {}},
                      {"niveaux": "RDC", "nombre_niveaux": 1, "affectation": "Accueil et services", "logements": {}},
                      {"niveaux": "R+2 à R+35", "nombre_niveaux": 34, "affectation": "Résidentiel courant",
                       "logements": {"A": 2, "B": 2}},
                      {"niveaux": "R+36 à R+38", "nombre_niveaux": 3, "affectation": "Résidentiel premium", "logements": {"C": 2}},
                      {"niveaux": "R+39", "nombre_niveaux": 1, "affectation": "Dernier niveau résidentiel",
                       "logements": {"Type C": 1, "Type D": 1}}]},
    3: {"type_page": "plan", "role_page": "plan_niveau", "niveau": "RDC", "unite_plan": "m",
        "pieces": _rooms(None, [("Grand hall réception", None), ("Conciergerie", None), ("Café / salon", None),
                                ("Hall / couloir commun", None), ("Sanitaires PMR", None), ("Local déchets", None)])},
    4: {"type_page": "plan", "role_page": "plan_type", "niveau": "Étage courant", "niveaux_couverts": "R+2 à R+35",
        "pieces": _rooms("Type A", [("Séjour / SAM", None), ("Chambre 2", None)]) + _rooms("Type B", [("Séjour / SAM", None)])
        + _rooms(None, [("Couloir commun", None)]),
        "logements": [{"type": "Type A", "surface_interieure_m2": 157, "exterieur_m2": 13, "nombre_sur_la_page": 2},
                      {"type": "Type B", "surface_interieure_m2": 117, "exterieur_m2": 11, "nombre_sur_la_page": 2}]},
    5: {"type_page": "plan", "role_page": "logement_type", "pieces": _rooms("Type A", A) + _rooms("Type A", [("Balcon", 13)], "non"),
        "logements": [{"type": "Type A", "surface_interieure_m2": 157, "exterieur_m2": 13}]},
    6: {"type_page": "plan", "role_page": "logement_type",
        "pieces": _rooms("Type B", B[:6]) + _rooms("Type C", [("Séjour / salle à manger", 52), ("SDB / WC", None)]),
        "logements": [{"type": "Type B", "surface_interieure_m2": 117, "exterieur_m2": 11},
                      {"type": "Type C", "surface_interieure_m2": 204, "exterieur_m2": 16}]},
    7: {"type_page": "plan", "role_page": "logement_type", "niveau": "R+39 / R+40",
        "pieces": _rooms("Type D", D[:5]) + _rooms(None, [("Lounge panoramique", None), ("Salon privé", None)]),
        "logements": [{"type": "Type D", "surface_interieure_m2": 248, "exterieur_m2": 32}]},
    8: {"type_page": "autre", "role_page": "cloisons", "pieces": [],
        "references": [{"type": "cloison", "texte": "C1 - ossature métallique 48 mm + 1 plaque 12,5/13 mm de chaque côté"}]},
    9: {"type_page": "autre", "role_page": "tableau",
        "pieces": _rooms("Type A", A) + _rooms("Type A", [("TOTAL INTERIEUR", 157), ("Balcon", 13)]) + _rooms("Type B", B),
        "logements": [{"type": "Type A", "surface_interieure_m2": 157, "exterieur_m2": 13},
                      {"type": "Type B", "surface_interieure_m2": 117, "exterieur_m2": 11}]},
    10: {"type_page": "autre", "role_page": "tableau", "pieces": _rooms("Type C", C) + _rooms("Type D", D),
         "logements": [{"type": "Type C", "surface_interieure_m2": 204, "exterieur_m2": 16},
                       {"type": "Type D", "surface_interieure_m2": 248, "exterieur_m2": 32}]},
    11: {"type_page": "autre", "role_page": "autre", "pieces": [],
         "logements": [{"type": "A", "nombre_total": 68}, {"type": "B", "nombre_total": 68}, {"type": "C", "nombre_total": 7},
                       {"type": "D", "nombre_total": 1}]},
}


def _read() -> dict:
    return plans._merge(PAGES, list(PAGES), {}, False, [], [])


def test_144_logements_68_68_7_1_et_surfaces_controlees():
    out = _read()
    t = {x["type"]: x for x in out["logements"]}
    assert out["total_logements"] == 144
    assert {k: v["nombre"] for k, v in t.items()} == {"A": 68, "B": 68, "C": 7, "D": 1}
    assert all(v["source_nombre"] == "programme" for v in t.values())
    assert {k: (v["somme_pieces_m2"], v["surface_interieure_m2"], v["controle"]) for k, v in t.items()} == {
        "A": (157, 157, "OK"), "B": (117, 117, "OK"), "C": (204, 204, "OK"), "D": (248, 248, "OK")}
    assert {k: v["exterieur_m2"] for k, v in t.items()} == {"A": 13, "B": 11, "C": 16, "D": 32}   # balcons à part
    assert t["A"]["pages"] == [5, 9] and t["A"]["pieces"] == 11
    assert not any("à vérifier" in r for r in out["remarques"])         # programme, plans d'étage et nombres écrits concordent


def test_chaque_type_compte_une_seule_fois_puis_multiplie():
    out = _read()
    rooms = out["pieces"]
    a = [r for r in rooms if r.get("logement") == "Type A"]
    assert len(a) == 12 and {r["page"] for r in a} == {9} and all(r["repetition"] == 68 for r in a)   # le tableau, pas la fiche
    assert next(r for r in a if r["nom"] == "Balcon")["plafond"] == "non" and not any(r["nom"].startswith("TOTAL") for r in a)
    assert sum(1 for r in rooms if r.get("logement") == "Type C") == 14            # tableau complet (la fiche p. 6 est partielle)
    couloir = next(r for r in rooms if r["nom"] == "Couloir commun")
    assert couloir["repetition"] == 34                                             # partie commune de l'étage courant × 34
    assert {r["nom"] for r in rooms if r["page"] == 3} >= {"Grand hall réception", "Conciergerie"}
    # surface intérieure totale des logements : 68 × 157 + 68 × 117 + 7 × 204 + 248 = 20 308 m² (plafonds à confirmer)
    assert out["total_plafond_a_confirmer_m2"] == 20308 and out["total_plafond_confirme_m2"] == 0


def test_metre_des_plafonds_par_type_et_rien_d_invente_sur_les_cloisons():
    out = _read()
    d = plan_quote.build(out, include_to_confirm=True)
    assert d["inputs"]["surface_plafond_m2"] == 20308
    labels = [s["label"] for s in d["steps"] if s["label"].startswith("Plafond")]
    assert "Plafond Séjour / salle à manger — Type A × 68 logements" in labels
    assert any("Hall / couloir commun" in m for m in d["missing"])                 # sans surface : signalé, jamais inventé
    assert not any(q["sku"] in ("MONTANT-M48", "UC-RAILS-48-MM") for q in d["quantities"])   # pas de cloison sans cotes
    assert len(d["pose"]) == 11 + 10 + 14 + 15 and all(p["repetition"] in (68, 7, 1) for p in d["pose"])   # pièces cotées


def test_une_contradiction_entre_pages_est_signalee():
    pages = {**PAGES, 4: {**PAGES[4], "logements": [{**PAGES[4]["logements"][0], "nombre_sur_la_page": 3},
                                                     PAGES[4]["logements"][1]]}}
    out = plans._merge(pages, list(pages), {}, False, [], [])
    assert any("Type A : 68 logements (programme) mais 102 d'après les plans d'étage" in r for r in out["remarques"])
    wrong = {**PAGES, 9: {**PAGES[9], "pieces": [r if r["nom"] != "Cuisine" or r["logement"] != "Type A" else {**r, "surface_m2": 20}
                                                 for r in PAGES[9]["pieces"]]}}
    out = plans._merge(wrong, list(wrong), {}, False, [], [])
    assert next(t for t in out["logements"] if t["type"] == "A")["controle"] == "écart : pièces 161 m² ≠ 157 m² déclarés"


def test_sans_logement_type_rien_ne_change():
    pages = {1: {"role_page": "plan_niveau", "niveau": "RDC", "pieces": _rooms(None, [("Salon", 20)], "oui")},
             2: {"role_page": "plan_niveau", "niveau": "R+1", "pieces": _rooms("Appartement 3", [("Salon", 22)], "oui")}}
    out = plans._merge(pages, [1, 2], {}, False, [], [])
    assert [(r["nom"], r["niveau"], r["repetition"]) for r in out["pieces"]] == [("Salon", "RDC", 1), ("Salon", "R+1", 1)]
    assert "logements" not in out and out["total_plafond_confirme_m2"] == 42
