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
