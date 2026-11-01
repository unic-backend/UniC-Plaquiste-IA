"""Studio vidéo : variété visuelle et rigueur de montage (idées retenues de lemo-opuscar, motion-video-kit, video-talkcraft).
12 ambiances de couleurs, lisibles, les MÊMES partout (moteur, serveur, API, agent, écran) ; règles de motion données au scénariste ;
contrôle du montage sans IA (accroche, texte dense, rythme, monotonie) montré au patron avant de lancer."""
import importlib.util
import re
from pathlib import Path

from app import agent, video_studio as vs

ROOT = Path(__file__).resolve().parents[2]
NEW = ("noir", "luxe", "papier", "pastel", "neon", "chantier")


def _engine():
    m = importlib.util.spec_from_file_location("video_spec_variete", ROOT / "scripts" / "video" / "spec.py")
    eng = importlib.util.module_from_spec(m)
    m.loader.exec_module(eng)
    return eng


def _css():
    """Palettes de scenes.html : {ambiance: {variable: #couleur}}."""
    html = (ROOT / "scripts" / "video" / "scenes.html").read_text(encoding="utf-8")
    return {m.group(1): dict(re.findall(r"--(\w+):(#[0-9a-fA-F]{3,6})", m.group(2)))
            for m in re.finditer(r'\[data-theme="(\w+)"\]\{([^}]*)\}', html)}


def _lum(h):
    h = h.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4   # noqa: E731
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_les_ambiances_sont_les_memes_partout():
    eng = _engine()
    css = _css()
    assert len(vs.THEMES) == 12 and set(NEW) <= set(vs.THEMES)
    assert tuple(eng.THEMES) == tuple(vs.THEMES) == tuple(css)                  # moteur, serveur, feuille de style : mêmes ambiances, même ordre
    assert vs._tool(False)["input_schema"]["properties"]["theme"]["enum"] == list(vs.THEMES)
    assert next(t for t in agent.TOOLS if t["name"] == "plan_video")["input_schema"]["properties"]["theme"]["enum"] == ["auto", *vs.THEMES]
    ts = (ROOT / "frontend" / "src" / "videoBoard.ts").read_text(encoding="utf-8")
    board = re.findall(r"^  (\w+): \{ name:", ts, re.M)
    assert board == list(vs.THEMES)                                             # l'écran propose les mêmes, dans le même ordre
    for k, v in re.findall(r'^  (\w+): \{ name: "[^"]+", bg: "(#\w+)"', ts, re.M):   # mêmes couleurs de fond que le moteur
        assert css[k]["royal"].lower() == v.lower(), k
    api = (ROOT / "backend" / "app" / "api_website.py").read_text(encoding="utf-8")
    assert all(k in re.search(r'theme: str = Field\("auto", pattern="\^\(([^)]*)\)\$"', api).group(1).split("|") for k in vs.THEMES)


def test_chaque_ambiance_se_lit_sur_un_telephone():
    for name, c in _css().items():
        assert _contrast(c["fg"], c["royal"]) >= 7, name                        # texte sur fond
        assert _contrast(c["gold"], c["royal"]) >= 3.5, name                    # accent sur fond (grands titres)
        assert _contrast(c["soft"], c["royal"]) >= 4.5, name                    # texte secondaire
        assert _contrast(c["cardfg"], c["cardbg"]) >= 7, name                   # chiffres sur leur carte


def test_une_ambiance_nouvelle_passe_jusqu_au_scenario():
    for k in NEW:
        spec = vs.build_spec("vertical", [{"type": "title", "l1": "TEST", "seconds": 3}], [], k)
        assert spec["theme"] == k
        assert _engine().clean(spec)["theme"] == k                              # le moteur l'accepte (sinon il retombait sur « unic »)
    assert vs.build_spec("vertical", [{"type": "title", "l1": "TEST", "seconds": 3}], [], "inconnue")["theme"] == "unic"


def test_le_scenariste_a_les_regles_de_motion_et_choisit_l_ambiance_du_sujet():
    assert "RÈGLES DE MOTION" in vs.SYSTEM and "ACCROCHE" in vs.SYSTEM and "jamais trois scènes de texte d'affilée" in vs.SYSTEM
    assert "pas toujours la même" in vs.SYSTEM
    desc = vs._tool(False)["input_schema"]["properties"]["theme"]["description"]
    assert all(k in desc for k in NEW)                                           # chaque ambiance est décrite : l'IA sait quand la choisir


def _scenes(*specs):
    return {"scenes": [{"type": t, "seconds": s, **extra} for t, s, extra in specs]}


def test_le_controle_du_montage_repere_ce_qui_rend_une_video_molle():
    assert vs.critique(_scenes(("title", 3, {}), ("photo", 4, {}))) == []          # trop court pour juger
    lent = vs.critique(_scenes(("title", 8, {"l1": "Bonjour"}), ("photo", 4, {}), ("photo", 4, {}), ("outro", 4, {})))
    assert any("première scène dure 8 s" in c for c in lent)
    dense = vs.critique(_scenes(("title", 3, {}), ("text", 6, {"heading": "Titre", "bullets": ["un deux trois quatre cinq six " * 6]}), ("photo", 4, {})))
    assert any("Scène 2 : 37 mots" in c and "coupe-la en deux" in c for c in dense)
    long_ = vs.critique(_scenes(("title", 3, {}), ("quote", 13, {"text": "Court"}), ("photo", 4, {})))
    assert any("Scène 2 : 13 s sur un même texte" in c for c in long_)
    mono = vs.critique(_scenes(("title", 3, {}), ("text", 4, {}), ("quote", 4, {}), ("photo", 4, {})))
    assert any("Les scènes 1 à 3 sont toutes du texte" in c for c in mono)
    plat = vs.critique(_scenes(*[("photo", 3, {})] * 5))
    assert plat == ["Toutes les scènes durent 3 s : varie le rythme (2 à 4 s pour l'énergie, plus long pour expliquer)."]
    sain = vs.critique(_scenes(("title", 3, {"l1": "Dakar"}), ("photo", 5, {}), ("stats", 6, {"items": [{"value": 1857, "label": "Fondation"}]}), ("outro", 3, {})))
    assert sain == []                                                              # une vidéo bien rythmée n'a aucun reproche
    assert len(vs.critique(_scenes(("title", 9, {}), ("text", 13, {"bullets": ["a " * 40]}), ("quote", 4, {}), ("text", 4, {}),
                                   ("text", 4, {})))) <= 3                         # trois conseils au plus : lisible d'un coup d'œil


def test_les_conseils_de_montage_accompagnent_le_scenario(monkeypatch):
    story = {"understood": "Une vidéo.", "assumptions": [], "limits": [], "theme": "chantier", "scenes": [
        {"type": "title", "l1": "CHANTIER", "seconds": 4}, {"type": "text", "heading": "Étape 1", "bullets": ["Ossature"], "seconds": 5},
        {"type": "text", "heading": "Étape 2", "bullets": ["Plaques"], "seconds": 5}, {"type": "quote", "text": "Très bien", "author": "Client", "seconds": 5},
        {"type": "outro", "lines": ["Merci"], "seconds": 3}]}
    monkeypatch.setattr(vs.settings, "anthropic_api_key", "cle-de-test")
    monkeypatch.setattr(vs, "images", lambda db=None: [])
    monkeypatch.setattr(vs, "_ask", lambda system, user, tool: story)
    p = vs.plan(None, "Une vidéo sur un chantier de plâtrerie", "vertical")
    assert p["spec"]["theme"] == "chantier"
    assert "Conseil de montage : Les scènes 1 à 3 sont toutes du texte" in p["note"]      # le conseil accompagne le scénario, avant de lancer
