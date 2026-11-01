"""Erreurs du fournisseur Claude : « crédit épuisé » seulement quand c'en est un, et la vraie raison du serveur est montrée (jamais une clé).
Avant : les mots « credit » ou « balance » dans n'importe quelle erreur faisaient dire « crédit épuisé » alors que la Console affichait du crédit."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ai  # noqa: E402


class Err(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status_code, self.message = status, message


CREDIT = "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."


@pytest.mark.parametrize("status,message", [
    (400, CREDIT), (402, "Payment required"), (400, "Your organization has exceeded its quota"), (400, "Insufficient balance"),
])
def test_un_vrai_credit_epuise_reste_un_credit_epuise(status, message):
    exc = Err(status, message)
    assert ai.classify_exc(exc) == "quota"
    texte = ai.explain_error(exc)
    assert texte.startswith("crédit Claude épuisé") and f"HTTP {status}" in texte and "console.anthropic.com" in texte


@pytest.mark.parametrize("message", ["tool failed: unpaid balance of client 12", "messages: credit note must be positive", "invalid balance field"])
def test_une_autre_erreur_qui_cite_credit_ou_balance_n_est_plus_un_credit_epuise(message):
    exc = Err(400, message)
    assert ai.classify_exc(exc) == "request"
    assert "épuisé" not in ai.explain_error(exc) and message.split(":")[0].lower() in ai.explain_error(exc)


def test_le_message_dit_la_vraie_raison_et_oriente_vers_la_cle_d_une_autre_organisation():
    texte = ai.explain_error(Err(400, CREDIT))
    assert "credit balance is too low" in texte
    assert "ANTHROPIC_API_KEY" in texte and "autre organisation" in texte


def test_le_relais_n_est_pas_renvoye_vers_la_cle_anthropic():
    texte = ai.explain_error(Err(402, "Payment required"), who="Vibecode", key_env="VIBECODE_API_KEY", console="vibecode.moe (crédits)")
    assert texte.startswith("crédit Vibecode épuisé") and "autre organisation" not in texte and "vibecode.moe" in texte


def test_jamais_de_cle_dans_la_raison_montree():
    exc = Err(402, "denied for key sk-ant-api03-ABCDEFGH12345678 and vk-1234567890abcdef : credit balance")
    texte = ai.explain_error(exc)
    assert "sk-ant" not in texte and "vk-1234" not in texte and "…" in texte


def test_les_autres_familles_ne_changent_pas():
    assert ai.classify_exc(Err(429, "rate limit exceeded")) == "rate"
    assert ai.classify_exc(Err(401, "invalid x-api-key")) == "auth"
    assert ai.classify_exc(Err(529, "overloaded")) == "server"
    assert "trop de requêtes" in ai.explain_error(Err(429, "rate limit"))
    assert "clé API refusée" in ai.explain_error(Err(401, "invalid x-api-key"))
    assert len(ai.server_reason(Err(400, "x" * 500))) <= 125
