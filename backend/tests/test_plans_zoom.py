"""Captures d'écran agrandies (zooms) : l'IA regarde un plan comme on le fait à l'écran — la page entière, puis des zones
agrandies là où une cote, un texte ou une jonction est trop petit. Valable pour un PDF de logiciel, un scan collé dans un PDF et
une photo de téléphone (pivotée, 12 Mpx). Le rendu et les découpes sont réels ; l'IA est simulée (pas de clé ici)."""
import base64
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app import pdfjob, plans
from app.database import SessionLocal
from app.main import app

A4 = (595, 842)
RED = (255, 0, 0)


def _img(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def _red_share(im: Image.Image) -> float:
    px = list(im.resize((60, 60)).getdata())
    return sum(1 for r, g, b in px if r > 200 and g < 80 and b < 80) / len(px)


def _scan() -> Image.Image:
    """Plan scanné A4 à 300 ppp : un carré rouge en haut à gauche, une petite cote au centre."""
    im = Image.new("RGB", (2480, 3508), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((248, 351, 744, 1052), fill=RED)          # x 0,10–0,30 ; y 0,10–0,30
    d.text((1150, 1750), "CUISINE 3,45 x 2,10", fill="black")
    return im


def _pdf(tmp_path, rotate: int = 0):
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    c.drawImage(ImageReader(_scan()), 0, 0, *A4)          # page 1 : scan
    c.showPage()
    c.setFillColorRGB(1, 0, 0)                             # page 2 : plan vectoriel, carré rouge en bas à droite
    c.rect(A4[0] * 0.6, A4[1] * 0.1, A4[0] * 0.3, A4[1] * 0.2, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 5)
    c.drawString(A4[0] * 0.65, A4[1] * 0.25, "SDB 2,40 x 1,80")
    c.drawString(60, 780, "SEJOUR")
    c.showPage()
    c.save()
    data = b.getvalue()
    if rotate:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(data)
        doc[1].set_rotation(rotate)
        out = io.BytesIO()
        doc.save(out)
        data = out.getvalue()
    p = tmp_path / f"plan{rotate}.pdf"
    p.write_bytes(data)
    return p


def _photo(tmp_path):
    """Photo de téléphone 4032 × 3024 prise « couchée » (EXIF orientation 6) : un carré rouge en haut à gauche une fois redressée."""
    upright = Image.new("RGB", (3024, 4032), "white")
    ImageDraw.Draw(upright).rectangle((0, 0, 756, 1008), fill=RED)   # x 0–0,25 ; y 0–0,25 de la photo redressée
    stored = upright.transpose(Image.Transpose.ROTATE_90)            # ce que le capteur enregistre
    exif = stored.getexif()
    exif[0x0112] = 6
    p = tmp_path / "photo.jpg"
    stored.save(p, exif=exif, quality=90)
    return p


def test_zoom_sur_un_plan_vectoriel_rend_la_zone_seule_en_haute_definition_avec_ses_textes(tmp_path):
    p = _pdf(tmp_path)
    z = pdfjob.run("zoom", path=str(p), index=1, box=[0.6, 0.7, 0.9, 0.9])
    im = _img(z["b64"])
    assert max(im.size) == 1428 and _red_share(im) > 0.9          # la zone seule (le carré rouge), à 576 ppp (× 8 : plafond)
    assert z["agrandissement"] >= 3                                # bien plus grand que sur la vue d'ensemble
    assert [w["t"] for w in z["words"]] == ["SDB 2,40 x 1,80"]     # les textes exacts de la zone, rien d'autre
    small = pdfjob.run("zoom", path=str(p), index=1, box=[0.62, 0.72, 0.625, 0.725])   # zone minuscule : élargie à 2 %
    assert small["zone"][2] - small["zone"][0] >= 0.019 and _red_share(_img(small["b64"])) > 0.9
    pct = pdfjob.run("zoom", path=str(p), index=1, box=[60, 70, 90, 90])                # donnée en pourcentages
    assert pct["zone"] == z["zone"]


def test_zoom_sur_une_page_pivotee_suit_ce_qu_on_voit(tmp_path):
    p = _pdf(tmp_path, rotate=90)
    page = pdfjob.run("page", path=str(p), index=1)
    over = _img(page["overview"])
    assert over.width > over.height                                # page affichée couchée
    # pivotée de 90° (sens horaire) : le carré du bas à droite passe en bas à gauche
    z = pdfjob.run("zoom", path=str(p), index=1, box=[0.1, 0.6, 0.3, 0.9])
    assert _red_share(_img(z["b64"])) > 0.9 and z["words"] == []   # textes en coordonnées non pivotées : pas donnés


def test_page_scannee_rendue_a_sa_resolution_d_origine_en_tuiles(tmp_path):
    p = _pdf(tmp_path)
    scan = pdfjob.run("page", path=str(p), index=0)
    vector = pdfjob.run("page", path=str(p), index=1)
    assert scan["scan"] and len(scan["tiles"]) >= 4                # 2 480 × 3 508 px : découpée, plus réduite à 1 568 px
    assert not vector["scan"] and vector["tiles"] == []            # A4 vectoriel : textes exacts + vue entière suffisent
    z = pdfjob.run("zoom", path=str(p), index=0, box=[0.08, 0.08, 0.32, 0.32])
    assert _red_share(_img(z["b64"])) > 0.6


def test_photo_de_telephone_redressee_en_tuiles_et_zoomable(tmp_path):
    p = _photo(tmp_path)
    v = pdfjob.run("photo", path=str(p))
    assert (v["w"], v["h"]) == (3000, 4000)                        # redressée (EXIF) puis bornée à 4 000 px
    assert len(v["tiles"]) == 9 and max(_img(v["overview"]).size) == 1568
    z = pdfjob.run("zoom", path=str(p), box=[0, 0, 0.25, 0.25])
    im = _img(z["b64"])
    assert _red_share(im) > 0.9 and max(im.size) == 1568 and z["agrandissement"] == 4.0
    assert _red_share(_img(pdfjob.run("zoom", path=str(p), box=[0.5, 0.5, 0.75, 0.75])["b64"])) == 0


# ---------- l'IA demande ses zooms ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(plans.settings, "anthropic_api_key", "test")
    with TestClient(app) as c:
        yield c


def _upload(client, path, mime) -> str:
    return client.post("/api/files", files={"file": (path.name, path.read_bytes(), mime)}).json()["id"]


def _script(answers: list[str], calls: list):
    def call(content):
        calls.append(content)
        return answers[min(len(calls), len(answers)) - 1]
    return call


def test_question_precise_l_ia_zoome_puis_repond(client, monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(plans, "_call", _script([
        '```json\n{"zooms": [{"page": 2, "zone": [0.6, 0.7, 0.9, 0.9]}]}\n```',
        "La salle de bain fait 2,40 × 1,80 m.",
    ], calls))
    fid = _upload(client, _pdf(tmp_path), "application/pdf")
    with SessionLocal() as db:
        out = plans.ask(db, fid, "Quelles sont les cotes de la SDB ?", page=2)
    assert len(calls) == 2 and out["reponse"].startswith("La salle de bain")
    first = [b["type"] for b in calls[0]]
    assert first == ["image", "text"] and "page 2" in calls[0][-1]["text"] and "ZOOM" in calls[0][-1]["text"]
    texts = [b["text"] for b in calls[1] if b["type"] == "text"]
    assert [b["type"] for b in calls[1]].count("image") == 2       # la page + la capture agrandie
    assert any("ZOOM 1 : page 2" in t and "SDB 2,40 x 1,80" in t for t in texts)
    assert out["zooms"] == [{"page": 2, "zone": [0.6, 0.7, 0.9, 0.9], "agrandissement": out["zooms"][0]["agrandissement"]}]
    assert calls[1][-1]["text"] == calls[0][-1]["text"]           # la consigne et la question restent les mêmes


def test_zoom_hors_des_pages_montrees_ou_page_inconnue(client, monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(plans, "_call", _script(['{"zooms": [{"page": 9, "zone": [0, 0, 1, 1]}]}'], calls))
    fid = _upload(client, _pdf(tmp_path), "application/pdf")
    with SessionLocal() as db:
        assert "illisible" in plans.ask(db, fid, "cote ?", page=1)["error"] and len(calls) == 1   # jamais un zoom inventé
        assert "introuvable" in plans.ask(db, fid, "cote ?", page=7)["error"]


def test_photo_lue_en_tuiles_et_zoom_demande_pendant_l_analyse(client, monkeypatch, tmp_path):
    calls: list = []
    first = {"unite_plan": "m", "pieces": [{"nom": "WC", "surface_m2": None, "plafond": "a_confirmer"}], "zooms": [[0, 0, 0.25, 0.25]]}
    final = {"unite_plan": "m", "pieces": [{"nom": "WC", "longueur_m": 1.2, "largeur_m": 1, "surface_m2": 1.2, "plafond": "oui",
                                            "raison": "FP"}], "zooms": []}
    monkeypatch.setattr(plans, "_call", _script([json.dumps(first), json.dumps(final)], calls))
    fid = _upload(client, _photo(tmp_path), "image/jpeg")
    with SessionLocal() as db:
        out = plans.analyze(db, fid)
    assert [b["type"] for b in calls[0]].count("image") == 10      # photo entière + 9 tuiles à sa résolution
    assert "tuile 9" in calls[0][-1]["text"] and "zooms" in calls[0][-1]["text"]
    assert [b["type"] for b in calls[1]].count("image") == 11 and out["pieces"][0]["surface_m2"] == 1.2


def test_page_d_un_dossier_relue_avec_un_zoom(client, monkeypatch, tmp_path):
    calls: list = []
    page = {"type_page": "plan", "niveau": "R+1", "unite_plan": "m", "pieces": [
        {"nom": "SDB", "longueur_m": 2.4, "largeur_m": 1.8, "surface_m2": 4.32, "plafond": "oui", "raison": "FP"}]}
    monkeypatch.setattr(plans, "_call", _script([json.dumps({**page, "zooms": [[0.6, 0.7, 0.9, 0.9]]}), json.dumps(page)], calls))
    fid = _upload(client, _pdf(tmp_path), "application/pdf")
    with SessionLocal() as db:
        out = plans.analyze(db, fid, budget_s=60)
    for job in list(plans._JOBS.values()):
        job["thread"].join(60)
    zoomed = [c for c in calls if any(b["type"] == "text" and b["text"].startswith("↑ ZOOM") for b in c)]
    assert zoomed and all(c[-1]["text"].startswith(plans.PAGE_PROMPT) for c in calls)
    assert out["lecture"]["zooms"] >= 1
    scan_page = next(c for c in calls if "PAGE 1 :" in c[-1]["text"])
    assert "PAGE SCANNÉE" in scan_page[-1]["text"]                 # le scan est signalé : cotes à lire sur l'image, zooms


def test_read_plan_passe_la_page_a_la_question(client, monkeypatch, tmp_path):
    from app.agent import AgentSession
    seen = {}
    monkeypatch.setattr(plans, "ask", lambda db, fid, q, page=None: seen.update(q=q, page=page) or {"reponse": "ok"})
    fid = _upload(client, _pdf(tmp_path), "application/pdf")
    with SessionLocal() as db:
        AgentSession(db, None, {"last_file_id": fid})("read_plan", {"question": "cote SDB ?", "page": 2})
    assert seen == {"q": "cote SDB ?", "page": 2}


def test_consignes_de_zoom():
    for prompt in (plans.PROMPT, plans.PAGE_PROMPT, plans.ASK_PROMPT):
        assert "ZOOM" in prompt and "0;0 = en haut à gauche" in prompt
