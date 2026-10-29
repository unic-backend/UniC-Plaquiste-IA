"""Règle du patron pour les cloisons : 2 montants côte à côte à chaque jonction de plaques (en 50 comme en 60 cm) et à chaque
angle droit. L'ancienne règle « montant de jonction partagé » est archivée de la mémoire, la fiche ossature mise à jour."""
from fastapi.testclient import TestClient

from app import memory
from app.main import app


def test_ancienne_regle_archivee_et_fiche_mise_a_jour():
    from app.database import SessionLocal
    from app.models import AppSetting, KnowledgeArticle, Memory
    from app.seed import _OLD_STUDS_TEXT, _NEW_STUDS_TEXT, apply_owner_studs_v9
    with TestClient(app), SessionLocal() as db:
        old = memory.add(db, "Cloison : chaque plaque (1,20 m de large) prend 3 montants, les deux bords et le milieu ; deux plaques "
                             "voisines partagent le montant de jonction.", kind="preference", source="user", pinned=True)
        art = db.query(KnowledgeArticle).filter(KnowledgeArticle.slug == "methode-ossature").first()
        art.body = _OLD_STUDS_TEXT + " Barres de 2,80 m : au-delà de 2,80 m de haut, rallonges.\nRails : longueur × 2."
        db.query(Memory).filter(Memory.text.like("Cloison : un montant tous les 60 cm%")).delete(synchronize_session=False)
        for flag in ("seed_owner_rules_v14", "seed_owner_studs_v9"):
            row = db.get(AppSetting, flag)
            if row:
                db.delete(row)
        db.commit()
        assert memory.seed_owner_rules(db) == 1
        db.refresh(old)
        assert old.state == "archived"
        assert any("2 montants côte à côte" in m.text for m in db.query(Memory).filter(Memory.state == "active"))
        assert apply_owner_studs_v9(db) == 1 and apply_owner_studs_v9(db) == 0
        db.refresh(art)
        assert art.body.startswith(_NEW_STUDS_TEXT) and "Rails" in art.body
