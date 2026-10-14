"""Book d'entreprise publié sur clic ; publication de pages qui survit à la refonte du site (appli React sans en-tête dans le HTML)."""
import base64
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("UNIC_DATA_DIR", "/tmp/unic-test-data")
os.environ.setdefault("UNIC_NO_BACKGROUND", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import website  # noqa: E402
from app.main import app  # noqa: E402

SPA_HOME = '<!doctype html><html><head><title>UniC</title><style>body{margin:0}</style></head><body><div id="root"></div></body></html>'


class Fake:
    """Faux site (accueil appli React) + faux GitHub."""
    def __init__(self, files=None):
        self.calls = []
        self.files = {"sitemap.xml": "<urlset>\n  <url><loc>https://www.unicplaquiste.com/</loc></url>\n</urlset>", "index.html": "<html>home</html>"}
        self.files.update(files or {})

    def __call__(self, method, url, **kw):
        self.calls.append((method, url))
        req = httpx.Request(method, url)
        if url == "https://www.unicplaquiste.com/":
            return httpx.Response(200, request=req, text=SPA_HOME)
        if url.endswith("/repos/unic-backend/site-unic-plaquiste"):
            return httpx.Response(200, request=req, json={"permissions": {"push": True}})
        if "/contents/" in url:
            path = url.split("/contents/", 1)[1]
            if method == "GET":
                if path in self.files:
                    return httpx.Response(200, request=req, json={"sha": "sha-" + path, "content": base64.b64encode(self.files[path].encode()).decode()})
                return httpx.Response(404, request=req, json={"message": "Not Found"})
            self.files[path] = base64.b64decode(kw["json"]["content"]).decode()
            return httpx.Response(201, request=req, json={"commit": {"html_url": "https://github.com/x/commit/abc"}})
        return httpx.Response(404, request=req)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def site(monkeypatch, client):
    fake = Fake()
    monkeypatch.setattr(website, "_http", fake)
    website._TPL_CACHE.update(t=0.0, data=None)
    client.delete("/api/website")
    yield fake
    client.delete("/api/website")
    website._TPL_CACHE.update(t=0.0, data=None)


def _connect(client):
    assert client.put("/api/website/connect", json={"token": "github_pat_" + "x" * 30}).status_code == 200


def test_pages_still_render_when_the_live_site_is_a_react_app(site):
    tpl = website.fetch_template()      # avant : « Le modèle du site a changé » → plus aucune page publiable
    assert tpl["header"].startswith('<header id="header"') and "nav-toggle" in tpl["header"] and "<footer>" in tpl["footer"]
    spec = website.parse("slug: faux-plafond-ba13-test\ndescription: " + "x" * 80 + "\n---\n" + ("Texte utile pour la page. " * 40))
    page = website.render_page("Faux plafond test", spec)
    assert 'content="unic-ai"' in page and 'id="header" class="scrolled"' in page and "var(--espresso)" in page


def test_book_contains_only_the_companys_own_real_data():
    h = website.book_html()
    assert 'content="unic-ai"' in h and 'rel="canonical" href="https://www.unicplaquiste.com/book/"' in h
    for real in ("+221 77 708 50 92", "Unicplaquiste@gmail.com", "013141677", "SN.DKR.2026.A.22010", "Khadige Farhat", "Stade Abdoulaye Wade"):
        assert real in h
    for foreign in ("0810 444 1447", "tegapeace88", "Tega", "tegadesigns", "Silicon Valley"):   # rien du brief d'une autre personne
        assert foreign not in h
    assert "gradient" not in h.lower()                                                         # consigne : aucun dégradé
    assert "realis-03-plafond-pvc" not in h and "realis-04-bureau" not in h                   # images « exemple » : jamais présentées comme chantiers


def test_book_images_are_all_known_site_files():
    known = {"logo-unic-512", "poster-03", "galerie-19", "service-10", "ref-stade-03", "ref-dakar-arena", "ref-uam", "ref-uam-04",
             "realis-01-plafond", "realis-02-cloisons", "realis-05-deco-murale", "realis-07-habillage-mural", "hero-salon-arches"}
    used = set(re.findall(r'/images/([a-z0-9-]+)\.webp', website.book_html()))
    assert used <= known, used - known


def test_book_preview_points_photos_to_the_live_site(client):
    h = client.get("/api/website/book/preview").json()["html"]
    assert 'src="/images/' not in h and 'src="https://www.unicplaquiste.com/images/poster-03.webp"' in h


def test_book_is_published_only_on_click_with_a_connected_site(client, site):
    assert client.post("/api/website/book/publish").status_code == 409          # site non connecté : rien n'est écrit
    assert not [c for c in site.calls if c[0] == "PUT"]
    _connect(client)
    r = client.post("/api/website/book/publish")
    assert r.status_code == 200 and r.json()["url"] == "https://www.unicplaquiste.com/book/"
    assert 'content="unic-ai"' in site.files["book/index.html"] and "Khadige Farhat" in site.files["book/index.html"]
    assert site.files["sitemap.xml"].count("<loc>https://www.unicplaquiste.com/book/</loc>") == 1 and "<priority>0.8</priority>" in site.files["sitemap.xml"]
    assert site.files["index.html"] == "<html>home</html>"                       # l'accueil n'est jamais touché
    written = {c[1].split("/contents/")[1] for c in site.calls if c[0] == "PUT"}
    assert written == {"book/index.html", "sitemap.xml"}


def test_republishing_the_book_updates_it_without_duplicating_the_sitemap(client, site):
    _connect(client)
    assert client.post("/api/website/book/publish").status_code == 200
    assert client.post("/api/website/book/publish").status_code == 200
    assert site.files["sitemap.xml"].count("/book/</loc>") == 1


def test_book_never_overwrites_a_page_it_did_not_create(client, site):
    site.files["book/index.html"] = "<html>page du patron faite à la main</html>"
    _connect(client)
    r = client.post("/api/website/book/publish")
    assert r.status_code == 409
    assert site.files["book/index.html"] == "<html>page du patron faite à la main</html>"


def test_ai_pages_cannot_take_the_book_address():
    with pytest.raises(website.WebsiteError, match="Adresse de page"):
        website.parse("slug: book\ndescription: " + "x" * 80 + "\n---\n" + ("Texte utile pour la page. " * 40))
