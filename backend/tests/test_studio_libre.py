"""Règle du patron : le Studio vidéo est LIBRE — il fait n'importe quelle vidéo du monde, pas seulement des chantiers.
Ses « yeux » (vision) ne supposent aucun sujet, sa mémoire n'y glisse pas les règles de devis, ses fichiers ne s'appellent plus « Plaquiste »."""
import io
import re
import zipfile

from fastapi.testclient import TestClient

from app import memory, video_studio, vision
from app.agent import TOOLS
from app.database import SessionLocal
from app.main import app


def test_les_yeux_ne_supposent_aucun_sujet():
    p = vision.FRAMES_PROMPT
    assert "N'IMPORTE QUEL sujet" in p and "animaux" in p and "Ne suppose aucun sujet" in p
    assert not re.search(r"plaquiste|BA13|faux plafond|intérieur en chantier|Dakar", p, re.I)
    assert "#numéro" in p and "Résumé" in p                                  # format attendu par parse_looks, inchangé


def test_la_memoire_du_studio_ecarte_les_regles_de_devis_mais_garde_les_gouts_video(monkeypatch):
    with TestClient(app), SessionLocal() as db:
        rule = memory.add(db, "Règle de devis : au-dessus de 100 m², ajouter 10 pièces de marge.", pinned=True)
        taste = memory.add(db, "Mes vidéos : toujours en vertical, musique calme, sous-titres jaunes.", pinned=True)
        found = memory.add(db, "Les lions de la réserve de Bandia chassent surtout le matin.")
        db.commit()
        monkeypatch.setattr(memory, "retrieve", lambda db, query, budget=0, **k: [
            memory.Hit(rule, 1.0, {"importance": 1}, always=True), memory.Hit(taste, 1.0, {"importance": 1}, always=True),
            memory.Hit(found, 0.6, {"match": 1.0})])
        got = video_studio._memory(db, "vidéo d'un lion")
        full = memory.block(db, "vidéo d'un lion")
    assert "sous-titres jaunes" in got and "Bandia" in got and "Règle de devis" not in got   # règle toujours rappelée, sans rapport : écartée
    assert "Règle de devis" in full                                                         # ailleurs (chat, devis), elle reste rappelée


def test_outil_plan_video_ouvert_a_tous_les_sujets():
    d = next(t for t in TOOLS if t["name"] == "plan_video")["description"]
    assert "N'IMPORTE QUEL sujet" in d and "pas forcément un chantier" in d and "photos du site, chiffres, avis" not in d


def test_le_fichier_video_ne_porte_plus_le_nom_du_metier(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("video.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    with TestClient(app), SessionLocal() as db:
        out = video_studio.save_zip(db, buf.getvalue(), 7, None)
    assert re.fullmatch(r"Video-UniC-\d{4}-\d{2}-\d{2}-\d{2}h\d{2}\.mp4", out["filename"]) and "Plaquiste" not in out["filename"]
