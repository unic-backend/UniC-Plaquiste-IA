"""Anti-vibecode : les 43 signes d'un site « fait par l'IA », donnés à Claude Code pour les projets web de UniC Code.

Source : skill `anti-vibecode` de Melvynx/shared-skills, copié dans `docs/anti-vibecode/`. Le serveur n'embarque pas ce dossier (le
Dockerfile ne copie que backend, frontend, scripts) : les règles sont donc reprises ici mot pour mot, et `tests/test_anti_vibecode.py` vérifie que les deux copies restent identiques."""
from __future__ import annotations

import re

# (numéro, signe, quoi faire à la place) : mêmes mots que `references/signs.md`
SIGNS: tuple[tuple[int, str, str], ...] = (
    ( 1, 'Purple gradient on a black background', 'One brand color, flat or a gradient of 2 close tones of it. Not purple unless the brand is purple.'),
    ( 2, 'Flat white background everywhere, nothing else', 'A tinted off-white or a real surface color, and at least one section that breaks the rhythm.'),
    ( 3, 'Neon colors (cyan, lime, magenta) on dark', 'Saturation from the brand palette, contrast from value, not from glow.'),
    ( 4, 'Glowing borders in dark mode', 'A 1 px border in a neutral 10-15 % lighter than the surface.'),
    ( 5, 'Tailwind indigo buttons', 'The brand color, tested for contrast on its background.'),
    ( 6, 'Grain over a gradient', 'Drop the gradient, or use a real photo or illustration.'),
    ( 7, 'Colored borders on every card', 'Neutral borders; color only on the one card that matters.'),
    ( 8, 'Big centered title with two buttons under it', 'Left-aligned hero with the product visible, one primary action.'),
    ( 9, 'Three feature cards side by side', 'Show the features working: screenshots, a demo, one feature per section.'),
    (10, 'Bento grid', 'Only if the content is really of different sizes; otherwise a plain list or a demo.'),
    (11, 'Rounded corners on everything', 'One radius scale (e.g. 6 px controls, 12 px cards), not the max everywhere.'),
    (12, 'A shadow under every card', 'Elevation only for what floats (menus, dialogs). Cards sit flat.'),
    (13, 'Liquid glass / glassmorphism', 'Solid surfaces. Blur only for a sticky header over content, if at all.'),
    (14, 'Dot grid in the background', 'Nothing, or a texture that belongs to the brand.'),
    (15, 'Big blurred blobs behind the hero', 'Nothing. Let the product image carry the hero.'),
    (16, 'Different spacing between every section', 'One vertical rhythm (a spacing scale) used everywhere.'),
    (17, 'Sparkles icon to say « AI »', 'Say what the AI does in words, or show it doing it.'),
    (18, 'Default Lucide icons on every feature', 'Fewer icons. Real product visuals, or a custom icon set with a point of view.'),
    (19, 'Emojis in titles', 'No emoji in headings.'),
    (20, 'Little green checks before every line', 'A plain list, or checks only in a comparison table.'),
    (21, 'Inter, Geist or Space Grotesk', 'A typeface chosen for the brand (and a second one for contrast if needed).'),
    (22, 'Instrument Serif in italics in the middle of the title', 'One heading style. Emphasis through weight or color, not a font switch.'),
    (23, 'Gradient on the hero title', 'Solid text color.'),
    (24, 'Counters scrolling to « 10,000+ users »', 'The real number, static, with its source. No number if there is none.'),
    (25, 'Hover animation on everything', 'Hover feedback on interactive elements only, subtle (color, not size).'),
    (26, 'Fade-in on every scroll', 'Content visible on load. Motion only where it explains something.'),
    (27, 'Animations that are way too slow', '150-250 ms for UI, never blocking reading.'),
    (28, "« It's not X, it's Y »", 'Say what it is, directly.'),
    (29, 'AI words: boost, revolutionize, unleash, seamless, effortless', 'Concrete verbs and the real result.'),
    (30, 'Em dashes everywhere', 'Commas, colons, two sentences.'),
    (31, '« New » badge above the title', 'Only for a real launch, with what is new and its date.'),
    (32, 'Fake testimonials with a generic avatar', 'Real quotes with name, role and link, or no testimonial section.'),
    (33, 'Three pricing tiers with « Most popular » in the middle', 'The real offer. One plan is fine.'),
    (34, 'Zero real demo of the product', 'Show the product working, first screen.'),
    (35, 'shadcn charts with no styling', 'Brand colors, real data, labeled axes.'),
    (36, 'The sun / moon toggle nobody asked for', 'Follow the system theme, or ship one theme done well.'),
    (37, 'No legal notice page (mentions légales / imprint)', 'A real page with the company details (TODO fields for the user).'),
    (38, 'No privacy policy', 'A real page, linked in the footer and the signup form.'),
    (39, 'The tab still says « Create Next App »', 'A real `<title>` per page: product name + what the page is.'),
    (40, 'The default Next / Vercel / Vite favicon', "The product's own favicon (and apple-touch-icon)."),
    (41, 'No Open Graph image (a shared link shows an empty card)', 'One og image per page, 1200x630, with the page title.'),
    (42, 'A footer full of links that lead nowhere', 'Only links that exist.'),
    (43, 'Pages that take forever to load', 'Optimized images, server rendering, no 3 MB hero video.'),
)

# Projet qui produit des pages web (site, landing, vitrine, interface) : les jeux, scripts et documents n'ont pas ces signes.
WEB_RE = re.compile(r"\b(site|sites|page|pages|landing|vitrine|portfolio|boutique|web|html|css|interface|tableau de bord|dashboard|"
                    r"front|react|appli web|application web)\b", re.I)

INTRO = ("DESIGN : ce projet est une page ou un site web. Évite ces 43 réflexes d'un site généré par IA (le patron veut un rendu fait par un humain). "
         "Avant d'écrire une page, décide en une ligne : une couleur de marque qui n'est pas violette ni indigo, une police qui n'est pas "
         "Inter, Geist ni Space Grotesk, une mise en page qui n'est pas un titre centré + 3 cartes. Pas de faux témoignage, faux chiffre ni "
         "faux logo : sans vraie donnée, retire le bloc. Pages légales (mentions légales, confidentialité) avec des champs TODO à remplir, "
         "jamais de fausses infos d'entreprise. Si la demande impose ses propres couleurs ou sa marque, la demande l'emporte.")


def wanted(*texts: str) -> bool:
    """Vrai si la demande (ou celle du projet qu'on continue) construit des pages web."""
    return any(WEB_RE.search(t or "") for t in texts)


def block() -> str:
    """Texte ajouté à la tâche de Claude Code : une ligne par signe, « à éviter → à faire »."""
    lines = [f"{n:02d}. {sign} → {instead}" for n, sign, instead in SIGNS]
    return INTRO + "\n" + "\n".join(lines)
