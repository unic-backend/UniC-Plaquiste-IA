"""Devis et bons sans IA cloud (mode secours) : « fais le devis cloison 3 x 2,5 pour Awa » reprenait le calcul PRÉCÉDENT de la
conversation (un autre chantier) ; un calcul partiel (surface seule, sans ossature) partait en devis sans prévenir. Le métré dit dans
la phrase passe maintenant en premier, et les garde-fous de l'IA (calcul partiel, contrôle indépendant) valent aussi ici."""
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import QuotationItem


def _say(c, message, cid=None):
    r = c.post("/api/chat", json={"message": message, **({"conversation_id": cid} if cid else {})}).json()
    st = (r["message"].get("meta") or {}).get("structured") or {}
    return r["conversation_id"], r["message"]["content"], st.get("quotation_id")


def _boards(qid):
    with SessionLocal() as db:
        return next(i.quantity for i in db.query(QuotationItem).filter(QuotationItem.quotation_id == qid) if "Plaque" in i.description)


def test_le_devis_prend_le_metre_dit_dans_la_phrase():
    with TestClient(app) as c:
        cid, _, _ = _say(c, "cloison 10 m x 2,5 m deux faces")                                   # 21 plaques
        cid, _, qid = _say(c, "fais le devis cloison 3 m x 2,5 m une face pour Awa Ndiaye", cid)
        assert qid and _boards(qid) == 4               # plan de pose 3 × 2,5, une face : 2 entières + 2 pour les morceaux
        cid, _, qid = _say(c, "fais le devis pour Awa Ndiaye", cid)                               # sans métré : le dernier calcul
        assert qid and _boards(qid) == 4


def test_pas_de_devis_ni_de_bon_sur_un_calcul_partiel_sans_le_demander():
    with TestClient(app) as c:
        cid, text, qid = _say(c, "cloison de 20 m2, fais le devis pour Awa Ndiaye")
        assert qid is None and "partiel" in text and "longueur et la hauteur" in text
        _, text, _ = _say(c, "crée le bon de commande", cid)
        assert "partiel" in text and "Bon de commande" not in text
        _, _, qid = _say(c, "fais le devis partiel quand même", cid)                              # demandé explicitement : fait
        assert qid
        _, _, qid = _say(c, "cloison 8 x 2,5, fais le devis pour Awa Ndiaye", cid)               # métré complet : devis normal
        assert qid and _boards(qid) == 18              # plan de pose 8 × 2,5, 2 faces : 12 entières + 6 pour les morceaux
