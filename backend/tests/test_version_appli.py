"""Étape 7 du diagnostic : le serveur annonce l'empreinte de l'interface en ligne ; l'appli du téléphone la compare à la sienne."""
import json

from fastapi.testclient import TestClient

from app import main


def test_ping_annonce_la_version_de_l_interface(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path)
    with TestClient(main.app) as c:
        assert c.get("/api/ping").json()["web_build"] == ""                     # pas d'interface compilée : rien à annoncer
        (tmp_path / "version.json").write_text(json.dumps({"build": "b22bbd400452"}), encoding="utf-8")
        assert c.get("/api/ping").json()["web_build"] == "b22bbd400452"
        (tmp_path / "version.json").write_text("pas du json", encoding="utf-8")
        assert c.get("/api/ping").json()["web_build"] == ""                     # fichier abîmé : jamais d'erreur
