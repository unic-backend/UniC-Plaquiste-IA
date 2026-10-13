"""Secrets enregistrés devenus illisibles (clé de chiffrement changée : `UNIC_SECRET_KEY` ajoutée ou modifiée, disque remplacé).

Sans ce contrôle, chaque connexion (Gmail, GitHub, LinkedIn…) dit simplement « non connecté » : le patron ne sait pas pourquoi.
Détection générale : un réglage chiffré (jeton Fernet, préfixe « gAAAAA ») que la clé actuelle ne déchiffre pas. Lecture seule : rien n'est effacé."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import secrets_box
from app.models import AppSetting

#: nom lisible des connexions ; une clé inconnue (future) est quand même signalée sous son nom technique
LABELS = {
    "mail_secret": "Gmail (Courrier)", "repair_gh_token": "GitHub (Atelier)", "repair_deploy_hook": "Render (publication)",
    "site_gh_token": "GitHub du site", "li_token": "LinkedIn", "li_client_secret": "LinkedIn", "ig_token": "Instagram",
    "ig_app_secret": "Instagram", "higgsfield_key_id": "Higgsfield", "higgsfield_key_secret": "Higgsfield", "elevenlabs_key": "Voix ElevenLabs",
    "gbp_client_secret": "Fiche Google", "gbp_refresh_token": "Fiche Google",
}
_FERNET_PREFIX = "gAAAAA"


def unreadable(db: Session) -> list[dict]:
    out, seen = [], set()
    for row in db.query(AppSetting).filter(AppSetting.value.like(f"{_FERNET_PREFIX}%")).all():
        if row.value.startswith(_FERNET_PREFIX) and secrets_box.decrypt(row.value) is None:   # LIKE ignore la casse en SQLite : on revérifie exactement
            label = LABELS.get(row.key, row.key)
            if label not in seen:
                seen.add(label)
                out.append({"key": row.key, "label": label})
    return out
