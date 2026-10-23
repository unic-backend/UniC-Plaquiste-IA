"""Actions affirmées sans être faites : le serveur compare la réponse aux outils qui ont réellement réussi."""
import pytest

from app.claims import unbacked


@pytest.mark.parametrize("reply, succeeded, expected", [
    ("J'ai créé le devis UC-2026-0001 pour M. Diop.", [], ["le devis"]),
    ("J'ai créé le devis UC-2026-0001 pour M. Diop.", ["create_quote"], []),
    ("J'ai besoin du nom du client pour créer le devis.", [], []),
    ("J'ai préparé le calcul ; veux-tu que je crée le devis ?", [], []),
    ("C'est noté : rendez-vous jeudi à 10 h avec Awa.", [], ["le rendez-vous"]),
    ("C'est noté : rendez-vous jeudi à 10 h avec Awa.", ["add_appointment"], []),
    ("J'ai envoyé l'e-mail à la banque.", ["save_email_draft"], ["l'envoi (l'assistant n'envoie jamais rien lui-même)"]),
    ("J'ai préparé le brouillon d'e-mail pour ta banque.", [], ["l'e-mail"]),
    ("J'ai lu ton mail, voici mon avis.", [], []),
    ("Le devis a été créé dans le message précédent.", [], []),
    ("Je n'ai pas créé le devis : il manque le client.", [], []),
    ("Je viens d'enregistrer le versement de 200 000 F.", [], ["le versement"]),
    ("Je l'ai bien enregistré dans ma mémoire.", [], ["la mémoire"]),
    ("J'ai calculé 12 plaques et 11 montants.", [], []),
    ("J'ai créé le PDF de la lettre.", ["make_pdf"], []),
    ("J'ai créé le PDF de la lettre.", [], ["le fichier"]),
    ("Voici le devis demandé.", [], []),
    ("C'est fait.", [], []),
])
def test_actions_affirmees(reply, succeeded, expected):
    assert unbacked(reply, succeeded) == expected


DOC_APPROVAL = "l'approbation (seul le patron approuve et signe)"
SENT = "l'envoi (l'assistant n'envoie jamais rien lui-même)"
CONTACT = "le contact d'une personne (l'assistant n'appelle et n'écrit à personne)"
PUBLISHED = "la publication (seul le patron publie)"


@pytest.mark.parametrize("reply, succeeded, expected", [
    # le diagnostic du 23/10 : 15 phrases sur 16 passaient sans alerte
    ("J'ai publié le post sur LinkedIn.", [], [PUBLISHED]),
    ("J'ai publié le post sur LinkedIn.", ["save_social_post_draft"], [PUBLISHED]),     # un brouillon n'est pas une publication
    ("J'ai mis à jour le devis UC-2026-0804.", [], ["le devis"]),
    ("J'ai mis à jour le devis UC-2026-0804.", ["revise_document"], []),
    ("J'ai validé la facture F-2026-012.", ["create_invoice"], [DOC_APPROVAL]),        # seul le patron approuve
    ("J'ai approuvé le devis.", [], [DOC_APPROVAL]),
    ("J'ai supprimé le rendez-vous de demain.", [], ["le rendez-vous"]),
    ("J'ai annulé le rendez-vous de jeudi.", ["update_appointment"], []),
    ("J'ai planifié une relance pour Awa le 15.", [], ["le rappel"]),
    ("J'ai planifié une relance pour Awa le 15.", ["set_collect_reminder"], []),
    ("J'ai ajouté le client Moussa Diop à tes contacts.", [], ["la fiche contact"]),
    ("J'ai ajouté le client Moussa Diop à tes contacts.", ["create_contact"], []),
    ("J'ai créé le visuel pour Instagram.", [], ["le visuel"]),
    ("J'ai appelé le client pour confirmer.", [], [CONTACT]),
    ("J'ai lancé la fabrication de la vidéo.", [], ["la vidéo"]),                       # le chat n'a aucun outil vidéo
    ("Le devis a été créé et le PDF est prêt.", [], ["le devis", "le fichier"]),
    ("Le devis a été créé et le PDF est prêt.", ["create_quote"], []),
    ("Voilà, ta facture est prête.", [], ["la facture"]),
    ("Le rendez-vous est bien noté pour jeudi 10 h.", [], ["le rendez-vous"]),
    ("C'est envoyé !", [], [SENT]),
    ("Rendez-vous noté pour jeudi 10 h.", [], ["le rendez-vous"]),
    ("Rendez-vous pris avec Awa jeudi à 9 h.", [], ["le rendez-vous"]),
    ("Devis prêt : UC-2026-0900.", [], ["le devis"]),
    ("Je t'ai envoyé le devis par e-mail.", ["create_quote"], [SENT]),
    ("Je viens d'envoyer la facture à Awa.", ["create_invoice"], [SENT]),
    ("J'ai transmis ta demande au fournisseur.", [], [CONTACT]),
    ("J'ai pris rendez-vous pour toi vendredi à 9 h.", [], ["le rendez-vous"]),
    ("J'ai relancé les clients en retard.", ["list_unpaid"], [CONTACT]),
])
def test_actions_inventees_detectees(reply, succeeded, expected):
    assert unbacked(reply, succeeded) == expected


@pytest.mark.parametrize("reply, succeeded", [
    # ce que l'IA dit correctement ne doit jamais déclencher d'alerte
    ("Veux-tu que je publie le post ?", []),
    ("Je peux mettre à jour le devis si tu veux.", []),
    ("Le devis sera prêt dès que tu me donnes les dimensions.", []),
    ("Une fois validé par toi, je pourrai créer la facture.", []),
    ("Tu as validé la facture hier.", []),
    ("La facture est prête à être créée : confirme ?", []),
    ("Est-ce que le devis est prêt ?", []),
    ("Si le devis est prêt, je te l'envoie en PDF.", []),
    ("J'ai appelé l'outil get_prices pour vérifier.", []),
    ("Je l'ai pas envoyé, il te reste à cliquer.", []),
    ("Comme tu me l'as dit, le rendez-vous est annulé par le client.", []),
    ("J'ai partagé mon avis sur le devis.", []),
    ("J'ai relancé le calcul avec 2 faces.", []),
    ("J'ai préparé le devis du client Diop.", ["create_quote"]),
    ("J'ai noté que tu préfères le BA13 hydrofuge.", []),
    ("Je t'ai préparé le calcul, voici les quantités.", []),
    ("Le devis UC-2026-0804 a été créé hier.", []),
    ("Le client a validé le devis.", []),
    ("Awa a confirmé le rendez-vous de jeudi 10 h.", []),
    ("J'ai fait le point sur tes devis en cours.", []),
    ("J'ai préparé le message de relance ci-dessous.", ["list_unpaid"]),
    ("Le devis est prêt : UC-2026-0900, 1 250 000 FCFA.", ["create_quote"]),
    ("Je n'ai rien envoyé : tu valides d'abord.", []),
    ("Je viens de vérifier les prix.", []),
    ("Bien reçu, merci.", []),
    ("Vous avez validé le devis.", []),
])
def test_pas_de_fausse_alerte(reply, succeeded):
    assert unbacked(reply, succeeded) == []


def test_document_deja_en_base_et_contexte_visiteur():
    from app.claims import VISITOR_FAMILIES, visitor_note
    # un devis qui existe déjà : le citer comme créé n'est pas inventer ; le dire « mis à jour » sans outil, si
    assert unbacked("Le devis UC-2026-0804 a été créé.", [], known={"UC-2026-0804"}) == []
    assert unbacked("J'ai mis à jour le devis UC-2026-0804.", [], known={"UC-2026-0804"}) == ["le devis"]
    assert unbacked("J'ai envoyé le devis UC-2026-0804.", [], known={"UC-2026-0804"}) == [SENT]    # jamais envoyé par l'IA
    # chat du site : la demande n'est transmise que si save_lead a réussi ; une visite n'est jamais confirmée par le robot
    assert unbacked("Votre demande a bien été transmise au gérant.", ["save_lead"], extra=VISITOR_FAMILIES) == []
    assert unbacked("Votre demande a bien été transmise au gérant.", [], extra=VISITOR_FAMILIES) == ["vos coordonnées"]
    assert unbacked("J'ai bien noté votre demande.", [], extra=VISITOR_FAMILIES) == ["vos coordonnées"]
    assert unbacked("Votre visite est confirmée pour jeudi 10 h.", ["save_lead"], extra=VISITOR_FAMILIES) == ["le rendez-vous"]
    assert "nom et votre numéro" in visitor_note(["vos coordonnées"]) and "rien n'est encore réservé" in visitor_note(["le rendez-vous"])


def test_chat_du_site_ne_confirme_jamais_une_visite(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, sitechat
    from app.database import SessionLocal
    assert "ne confirmes et ne réserves JAMAIS" in sitechat.system_prompt()
    with TestClient(main.app), SessionLocal() as db:
        a = sitechat.reply(db, None, "Vous pouvez passer jeudi 10 h ?", "5.6.7.8", "/", model_call=lambda db, sess, turns: "Parfait, votre visite est confirmée pour jeudi 10 h.")
        assert "rien n'est encore réservé" in a["reply"]                              # le visiteur ne repart pas avec une fausse réservation
        b = sitechat.reply(db, a["session_id"], "Merci", "5.6.7.8", "/", model_call=lambda db, sess, turns: "Votre demande a bien été transmise au gérant.")
        assert "nom et votre numéro" in b["reply"]                                    # sans fiche prospect, rien n'est transmis : on le dit

        def with_lead(db, sess, turns):
            sitechat._save_lead(db, sess, {"name": "Awa Ndiaye", "phone": "+221 77 555 44 33", "need": "plafond"})
            return "Votre demande a bien été transmise au gérant."
        c = sitechat.reply(db, a["session_id"], "Awa Ndiaye, 77 555 44 33", "5.6.7.8", "/", model_call=with_lead)
        assert c["reply"] == "Votre demande a bien été transmise au gérant."


def test_numeros_de_documents_reconnus_en_base():
    from fastapi.testclient import TestClient
    from app import main, orchestrator
    from app.database import SessionLocal
    from app.models import Quotation
    with TestClient(main.app), SessionLocal() as db:
        if db.query(Quotation).filter(Quotation.number == "UC-2026-0999-ZZ").first() is None:
            db.add(Quotation(number="UC-2026-0999-ZZ"))
            db.commit()
        text = "Le devis UC-2026-0999-ZZ a été créé ; la facture UC-2026-0999-ZZ-F n'existe pas encore, UC-2099-0001-XX non plus."
        assert orchestrator.known_documents(db, text) == {"UC-2026-0999-ZZ"}
        assert orchestrator.known_documents(db, "Aucun numéro ici.") == set()


def test_un_numero_proche_ne_couvre_pas_un_autre_document():
    # le devis existe, pas sa facture : « la facture …-F a été créée » sans outil reste une invention
    assert unbacked("La facture UC-2026-0999-ZZ-F a été créée.", [], known={"UC-2026-0999-ZZ"}) == ["la facture"]
    assert unbacked("La facture UC-2026-0999-ZZ-F a été créée.", [], known={"UC-2026-0999-ZZ-F"}) == []
