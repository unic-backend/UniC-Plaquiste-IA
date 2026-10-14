from app import visit_report as vr


def test_mesures_et_absences():
    m = vr.mesurer("Bonjour. Tu as vu la fissure ? Oui, au plafond.", 60)
    assert m["mots"] == 9 and m["questions"] == 1 and m["mots_par_minute"] == 9.0
    m = vr.mesurer("abc", None)
    assert m["duree_secondes"] is None and m["mots_par_minute"] is None
    assert vr.mesurer(None)["mots"] == 0
    assert vr.mesurer("a b", True)["duree_secondes"] is None


def test_texte_trop_court_refuse():
    assert vr.preparer("ok")["valide"] is False


def test_consignes_et_troncature():
    r = vr.preparer("mot " * 20000)
    assert r["valide"] and r["tronque"] and len(r["texte"]) <= vr.MAX_CHARS
    assert "non précisé" in r["consignes"] and "DÉCIDÉ" in r["consignes"]


def test_outil_agent_branche():
    from app import agent
    assert any(t["name"] == "visit_report" for t in agent.TOOLS)
    assert hasattr(agent.AgentSession, "_t_visit_report")
