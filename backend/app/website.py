"""Site web unicplaquiste.com (Netlify, dépôt GitHub) : pages de contenu rédigées par l'IA, publiées après approbation.

Le site est un dossier de fichiers statiques déployé par Netlify à chaque commit sur la branche `main`. Ce module :
 - fabrique une page au même style que l'accueil (CSS, en-tête et pied de page repris du site en ligne) ;
 - la publie en un commit `/<slug>/index.html`, et ajoute l'adresse au `sitemap.xml` ;
 - n'écrit JAMAIS ailleurs : `index.html`, `_redirects`, `_headers`… sont intouchables, et une page qu'il n'a pas créée n'est jamais écrasée.
Le jeton GitHub (accès au seul dépôt du site) est chiffré (secrets_box) et jamais renvoyé.
"""
from __future__ import annotations

import base64
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app import secrets_box
from app.models import AppSetting

DEFAULT_REPO = "unic-backend/site-unic-plaquiste"
DEFAULT_BRANCH = "main"
SITE_URL = "https://www.unicplaquiste.com"
GENERATOR = "unic-ai"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){0,7}$")
RESERVED = {"images", "index", "404", "favicon", "robots", "sitemap", "unic-logo", "apple-touch-icon", "assets", "api", "app", "expert", "admin", "book"}
_TPL_CACHE: dict = {"t": 0.0, "data": None}


class WebsiteError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _get(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else ""


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def _http(method: str, url: str, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=40, follow_redirects=True) as client:
            return client.request(method, url, **kw)
    except httpx.HTTPError:
        raise WebsiteError("Impossible de joindre le service depuis le serveur. Réessaie dans un instant.", 502)


def _token(db: Session) -> str:
    raw = _get(db, "site_gh_token")
    return (secrets_box.decrypt(raw) or "") if raw else ""


def status(db: Session) -> dict:
    return {"connected": bool(_token(db)), "repo": _get(db, "site_gh_repo") or DEFAULT_REPO,
            "branch": _get(db, "site_gh_branch") or DEFAULT_BRANCH, "site_url": SITE_URL}


# ---------- GitHub ----------

def _gh(method: str, path: str, token: str, **kw) -> httpx.Response:
    return _http(method, f"https://api.github.com{path}", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, **kw)


def _explain(r: httpx.Response) -> WebsiteError:
    try:
        msg = (r.json().get("message") or "")[:160]
    except Exception:
        msg = ""
    if r.status_code in (401, 403):
        return WebsiteError("GitHub refuse ce jeton : il doit avoir le droit « Contents : Read and write » sur le dépôt du site. " + msg, 400)
    if r.status_code == 404:
        return WebsiteError("Dépôt introuvable avec ce jeton : vérifie le nom du dépôt et que le jeton y a accès.", 400)
    return WebsiteError(f"GitHub a refusé la demande. {msg}".strip(), 502)


def connect(db: Session, token: str, repo: str = "", branch: str = "") -> dict:
    token, repo, branch = (token or "").strip(), (repo or DEFAULT_REPO).strip(), (branch or DEFAULT_BRANCH).strip()
    if len(token) < 20 or any(c.isspace() for c in token):
        raise WebsiteError("Jeton invalide : colle-le en entier, sans espace.")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[\w./-]+", branch):
        raise WebsiteError("Nom de dépôt ou de branche invalide.")
    r = _gh("GET", f"/repos/{repo}", token)
    if r.status_code != 200:
        raise _explain(r)
    if not (r.json().get("permissions") or {}).get("push"):
        raise WebsiteError("Ce jeton peut lire le dépôt mais pas y écrire : donne-lui « Contents : Read and write ».")
    _put(db, "site_gh_token", secrets_box.encrypt(token))
    _put(db, "site_gh_repo", repo)
    _put(db, "site_gh_branch", branch)
    return status(db)


def disconnect(db: Session) -> dict:
    _put(db, "site_gh_token", "")
    return status(db)


# ---------- page : format du texte ----------

def parse(body: str) -> dict:
    """Texte du brouillon → {slug, description, blocks}. Format : lignes « slug: » et « description: », une ligne « --- », puis le contenu."""
    head, sep, content = (body or "").partition("\n---")
    if not sep:
        raise WebsiteError("Format attendu : « slug: … », « description: … », une ligne « --- », puis le texte de la page.")
    meta = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        if v:
            meta[k.strip().lower()] = v.strip()
    slug, desc = meta.get("slug", ""), meta.get("description", "")
    if not SLUG_RE.match(slug) or slug in RESERVED:
        raise WebsiteError("Adresse de page (slug) invalide : minuscules, chiffres et tirets, ex. faux-plafond-ba13-almadies.")
    if not 60 <= len(desc) <= 170:
        raise WebsiteError(f"La description Google doit faire 60 à 170 caractères (actuellement {len(desc)}).")
    blocks: list[tuple[str, object]] = []
    para: list[str] = []
    items: list[str] = []

    def flush():
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()
        if items:
            blocks.append(("ul", list(items)))
            items.clear()

    for raw in content.strip("\n").splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("## "):
            flush(); blocks.append(("h2", line[3:].strip()))
        elif line.startswith("### "):
            flush(); blocks.append(("h3", line[4:].strip()))
        elif line.startswith(("- ", "• ")):
            if para:
                flush()
            items.append(line[2:].strip())
        else:
            if items:
                flush()
            para.append(line)
    flush()
    words = sum(len(str(b[1]).split()) for b in blocks)
    if words < 120:
        raise WebsiteError(f"Page trop courte ({words} mots) : Google préfère au moins 150 mots utiles.")
    return {"slug": slug, "description": desc, "blocks": blocks, "words": words}


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _content_html(blocks) -> str:
    out = []
    for kind, val in blocks:
        if kind == "p":
            out.append(f"<p>{_esc(val)}</p>")
        elif kind in ("h2", "h3"):
            out.append(f"<{kind}>{_esc(val)}</{kind}>")
        else:
            out.append("<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in val) + "</ul>")
    return "\n".join(out)


# ---------- page : habillage repris du site en ligne ----------

_BUILTIN_TPL = {
    "links": ('<link rel="preconnect" href="https://fonts.googleapis.com">'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Barlow:wght@400;500;600;700&display=swap">'
              '<link rel="icon" href="/favicon.ico"><link rel="apple-touch-icon" href="/apple-touch-icon.png">'),
    "css": """:root{--ink:#02083a;--ink-soft:#33406b;--espresso:#02083a;--cream:#ffefa3;--gold:#ffc400;--serif:"Anton","Impact",sans-serif;--sans:"Barlow",system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;font-family:var(--sans);background:#f6f7fd;color:var(--ink);-webkit-font-smoothing:antialiased}
a{color:#071a7d}
.skip-link{position:absolute;left:12px;top:-60px;background:var(--gold);color:var(--ink);padding:10px 16px;border-radius:10px;font-weight:700;z-index:100}.skip-link:focus{top:12px}
#header{position:fixed;top:0;left:0;right:0;z-index:40;background:var(--espresso);color:#fff}
#header .hd{max-width:1180px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 24px}
#header .brand{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;font-family:var(--serif);letter-spacing:.04em;font-size:1.15rem}
#header .brand img{width:36px;height:36px;border-radius:10px}
#header .nav-links{display:flex;gap:6px}
#header .nav-links a{color:#fff;text-decoration:none;font-weight:600;padding:8px 12px;border-radius:999px}
#header .nav-links a:hover{background:rgba(255,255,255,.14)}
.nav-toggle{display:none;background:transparent;border:1.5px solid rgba(255,255,255,.5);border-radius:10px;width:42px;height:38px;cursor:pointer}
.nav-toggle span,.nav-toggle span::before,.nav-toggle span::after{display:block;width:18px;height:2px;background:#fff;margin:0 auto;position:relative}
.nav-toggle span::before,.nav-toggle span::after{content:"";position:absolute;left:0}
.nav-toggle span::before{top:-6px}.nav-toggle span::after{top:6px}
.menu-backdrop{display:none}
@media(max-width:760px){
  .nav-toggle{display:block}
  #header .nav-links{display:none;position:absolute;top:100%;left:0;right:0;flex-direction:column;background:var(--espresso);padding:8px 16px 16px}
  #header.menu-open .nav-links{display:flex}
  #header.menu-open .menu-backdrop{display:block;position:fixed;inset:0;z-index:-1}
}
footer{background:var(--espresso);color:var(--cream);padding:28px 24px;text-align:center;font-size:.95rem}
footer a{color:var(--cream)}""",
    "header": ('<header id="header"><div class="hd"><a class="brand" href="/"><img src="/images/logo-unic-512.webp" width="36" height="36" alt="">UNIC PLAQUISTE</a>'
               '<button class="nav-toggle" type="button" aria-expanded="false" aria-label="Menu"><span></span></button>'
               '<nav class="nav-links" aria-label="Menu principal"><a href="/">Accueil</a><a href="/#services">Services</a><a href="/book/">Book</a><a href="/#contact">Contact</a></nav></div>'
               '<div class="menu-backdrop"></div></header>'),
    "footer": ('<footer><p>© <span id="year">2026</span> UniC Plaquiste · Gueule Tapée, Dakar · <a href="tel:+221777085092">+221 77 708 50 92</a> · '
               '<a href="/">Retour au site</a></p></footer>'),
}


def fetch_template() -> dict:
    now = time.time()
    if _TPL_CACHE["data"] and now - _TPL_CACHE["t"] < 3600:
        return _TPL_CACHE["data"]
    r = _http("GET", SITE_URL + "/")
    if r.status_code != 200:
        raise WebsiteError("Le site en ligne est illisible pour le moment : réessaie dans un instant.", 502)
    page = r.text
    styles = re.findall(r"<style[^>]*>(.*?)</style>", page, flags=re.S)
    css = max(styles, key=len) if styles else ""
    header = re.search(r"<header id=\"header\".*?</header>", page, flags=re.S)
    footer = re.search(r"<footer>.*?</footer>", page, flags=re.S)
    fonts = re.findall(r"<link[^>]+(?:fonts\.googleapis|fonts\.gstatic|rel=\"icon\"|rel=\"apple-touch-icon\")[^>]*>", page)
    if not (css and header and footer):
        # Le site actuel est une appli (React) : son en-tête et son pied de page ne sont pas dans le HTML reçu.
        # Habillage de secours aux couleurs du site (bleu roi et or) : la publication de pages ne tombe pas en panne.
        _TPL_CACHE.update(t=now, data=_BUILTIN_TPL)
        return _BUILTIN_TPL
    data = {"css": css, "header": header.group(0), "footer": footer.group(0), "links": "\n".join(fonts)}
    _TPL_CACHE.update(t=now, data=data)
    return data


def _fix_nav(fragment: str) -> str:
    """Les liens d'ancre de l'accueil (#services…) doivent mener à l'accueil depuis une autre page."""
    out = re.sub(r'href="#top"', 'href="/"', fragment)
    out = re.sub(r'href="#(?!")', 'href="/#', out)
    return out


MENU_JS = """(function(){var h=document.getElementById('header'),t=document.querySelector('.nav-toggle'),b=document.querySelector('.menu-backdrop');
function s(o){h.classList.toggle('menu-open',o);t.setAttribute('aria-expanded',o?'true':'false');document.body.style.overflow=o?'hidden':'';}
t.addEventListener('click',function(){s(!h.classList.contains('menu-open'))});b.addEventListener('click',function(){s(false)});
document.querySelectorAll('.nav-links a').forEach(function(a){a.addEventListener('click',function(){s(false)})});
document.getElementById('year').textContent=new Date().getFullYear();})();"""


def render_page(title: str, spec: dict, tpl: dict | None = None) -> str:
    tpl = tpl or fetch_template()
    url = f"{SITE_URL}/{spec['slug']}/"
    t = _esc(title.strip())
    d = _esc(spec["description"])
    header = _fix_nav(tpl["header"]).replace('<header id="header"', '<header id="header" class="scrolled"', 1)
    footer = _fix_nav(tpl["footer"])
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "WebPage", "name": title.strip(), "description": spec["description"], "url": url,
        "inLanguage": "fr-SN", "isPartOf": {"@type": "WebSite", "name": "UniC Plaquiste", "url": SITE_URL + "/"},
        "about": {"@type": "LocalBusiness", "name": "UniC Plaquiste", "url": SITE_URL + "/"},
        "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Accueil", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": title.strip(), "item": url}]},
    }, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="generator" content="{GENERATOR}" />
<title>{t} | UniC Plaquiste</title>
<meta name="description" content="{d}" />
<link rel="canonical" href="{url}" />
<meta name="robots" content="index, follow, max-image-preview:large" />
<meta property="og:type" content="article" />
<meta property="og:title" content="{t}" />
<meta property="og:description" content="{d}" />
<meta property="og:url" content="{url}" />
<meta property="og:site_name" content="UniC Plaquiste" />
<meta property="og:image" content="{SITE_URL}/unic-logo.jpg" />
<meta property="og:locale" content="fr_FR" />
<meta name="twitter:card" content="summary_large_image" />
{tpl['links']}
<script type="application/ld+json">{ld}</script>
<style>{tpl['css']}
.page-art{{max-width:820px;margin:0 auto;padding:150px 28px 70px}}
.page-art h1{{font-family:var(--serif);font-size:clamp(2rem,5vw,3rem);line-height:1.1;margin:0 0 22px;color:var(--ink)}}
.page-art h2{{font-family:var(--serif);font-size:1.6rem;margin:38px 0 10px;color:var(--ink)}}
.page-art h3{{font-size:1.2rem;margin:26px 0 8px;color:var(--ink)}}
.page-art p,.page-art li{{font-size:1.06rem;line-height:1.75;color:var(--ink-soft)}}
.page-art ul{{padding-left:22px;margin:10px 0 18px}}
.page-art .cta-box{{margin-top:44px;padding:26px;border-radius:18px;background:var(--espresso);color:var(--cream)}}
.page-art .cta-box a{{display:inline-block;margin-top:12px;padding:12px 22px;border-radius:999px;background:var(--gold);color:var(--espresso);font-weight:700;text-decoration:none}}
.reveal-up,.wreveal .w{{opacity:1!important;transform:none!important}}
</style>
</head>
<body>
<a href="#main" class="skip-link">Aller au contenu</a>
{header}
<main id="main" class="page-art">
<nav aria-label="Fil d'Ariane" style="font-size:.9rem;margin-bottom:18px"><a href="/">Accueil</a> › {t}</nav>
<h1>{t}</h1>
{_content_html(spec['blocks'])}
<div class="cta-box"><b>Un projet à Dakar ? Devis gratuit.</b><br><a href="https://wa.me/221777085092" rel="noopener">Écrire sur WhatsApp</a></div>
</main>
{footer}
<script>{MENU_JS}</script>
</body>
</html>
"""


# ---------- publication ----------

def _contents(db: Session, path: str, ref: str) -> tuple[str, str] | None:
    r = _gh("GET", f"/repos/{_get(db, 'site_gh_repo') or DEFAULT_REPO}/contents/{path}", _token(db), params={"ref": ref})
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise _explain(r)
    j = r.json()
    return j["sha"], base64.b64decode(j.get("content", "")).decode("utf-8", "replace")


def _write(db: Session, path: str, text: str, sha: str | None, message: str, branch: str) -> str:
    body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode(), "branch": branch}
    if sha:
        body["sha"] = sha
    r = _gh("PUT", f"/repos/{_get(db, 'site_gh_repo') or DEFAULT_REPO}/contents/{path}", _token(db), json=body)
    if r.status_code not in (200, 201):
        raise _explain(r)
    return r.json().get("commit", {}).get("html_url", "")


def _commit_page(db: Session, slug: str, page: str, message: str, priority: str = "0.7") -> str:
    """Écrit `/<slug>/index.html` (jamais une page que l'assistant n'a pas créée) puis ajoute l'adresse au sitemap."""
    branch = _get(db, "site_gh_branch") or DEFAULT_BRANCH
    path = f"{slug}/index.html"
    existing = _contents(db, path, branch)
    if existing and f'content="{GENERATOR}"' not in existing[1]:
        raise WebsiteError("Cette adresse existe déjà sur le site et n'a pas été créée par l'assistant : choisis un autre slug.", 409)
    commit = _write(db, path, page, existing[0] if existing else None, message, branch)
    sm = _contents(db, "sitemap.xml", branch)
    if sm:
        loc = f"<loc>{SITE_URL}/{slug}/</loc>"
        if loc not in sm[1] and "</urlset>" in sm[1]:
            entry = (f"  <url>\n    {loc}\n    <lastmod>{datetime.now(timezone.utc).date().isoformat()}</lastmod>\n"
                     f"    <changefreq>monthly</changefreq>\n    <priority>{priority}</priority>\n  </url>\n")
            _write(db, "sitemap.xml", sm[1].replace("</urlset>", entry + "</urlset>"), sm[0], f"Sitemap : {slug}", branch)
    return commit


def publish(db: Session, title: str, body: str) -> dict:
    if not _token(db):
        raise WebsiteError("Le site n'est pas connecté (Paramètres → Site web).", 409)
    spec = parse(body)
    page = render_page(title, spec)
    commit = _commit_page(db, spec["slug"], page, f"Page « {title.strip()[:60]} » (rédigée par l'assistant, approuvée par le patron)")
    return {"url": f"{SITE_URL}/{spec['slug']}/", "commit": commit, "words": spec["words"]}


# ---------- Book d'entreprise : une page complète, écrite une fois, publiée sur clic du patron ----------

BOOK_SLUG = "book"
_BOOK_FILE = Path(__file__).with_name("site_pages") / "book.html"


def book_html(preview: bool = False) -> str:
    """Le Book tel qu'il sera publié. Aperçu : les photos pointent vers le site en ligne (elles y sont déjà)."""
    text = _BOOK_FILE.read_text(encoding="utf-8")
    return text.replace('src="/images/', f'src="{SITE_URL}/images/') if preview else text


def publish_book(db: Session) -> dict:
    if not _token(db):
        raise WebsiteError("Le site n'est pas connecté (Paramètres → Site web).", 409)
    commit = _commit_page(db, BOOK_SLUG, book_html(), "Book d'entreprise (publié sur clic du patron)", "0.8")
    return {"url": f"{SITE_URL}/{BOOK_SLUG}/", "commit": commit}
