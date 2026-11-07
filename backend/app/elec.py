"""Électricité et climatisation : repères FIABLES et calculs faits en code, pour conseiller le patron (UniC ne vend pas ces travaux :
ils restent exclus des devis). Chaque règle cite sa source ; rien n'est inventé.

Référence : NF C 15-100 (norme française des installations basse tension, logements : art. 10.1.4.7.2, tableau 10-1f), reprise par les
fabricants (Nexans, Legrand). Au Sénégal, l'ASN publie sa propre norme d'installations basse tension (bâtiments, ≤ 1 000 V alternatif) :
son texte n'a pas pu être consulté ici, la NF C 15-100 sert donc de repère, à confirmer pour un chantier réel. Tension du réseau : 230 V /
50 Hz (sources secondaires). Une photo ou un calcul ne remplace ni un électricien qualifié ni les mesures sur place.
"""
from __future__ import annotations

import math

U_MONO = 230.0
RHO_CU = 0.0225          # Ω·mm²/m : cuivre à température de service (valeur des calculs NF C 15-100 de chute de tension)
DROP_LIMIT = {"eclairage": 3.0, "autre": 5.0}   # % depuis le compteur, réseau public basse tension
BTU_PER_W = 3.412        # 1 W = 3,412 BTU/h (définition physique)
CLIM_SIZES_BTU = (7000, 9000, 12000, 18000, 24000)   # tailles courantes des splits muraux
CLIM_W_M2 = (100, 125)   # W froid par m² (2,50 m sous plafond) : 100 W/m², 100 à 125 pour un logement ancien ou mal isolé

SOURCES = {
    "nfc15100_tableau": "https://home.nexans.fr/app/uploads/2022/03/Tableau-section-et-calibres.pdf",
    "legrand_infographie": "https://assets.legrand.com/editorial/legrandfr/normes/infographie-norme-nfc15100-grand-public.pdf",
    "couleurs": "https://particuliers.engie.fr/electricite/conseils-electricite/conseils-installation-electrique/couleur-fils-electriques.html",
    "differentiel": "https://www.legrand.fr/questions-frequentes/combien-de-disjoncteurs-divisionnaires-par-interrupteur-differentiel",
    "type_a": "https://www.123elec.com/faq-interrupteur-differentiel",
    "chute_tension": "https://www.voltflow.net/blog/chute-de-tension-calcul-nf-c-15-100",
    "clim_100w": "https://www.jechange.fr/energie/electricite/news/clim-mal-dimensionnee-regle-100-watts-m2",
    "clim_m2": "https://www.hellowatt.fr/pompe-a-chaleur/climatisation/puissance-m2",
    "clim_pose": "https://www.espace-aubade.fr/blog/climatisation/installation-climatisation-etapes-pose-reglementation.html",
    "clim_notice": "https://www.daikinmea.com/content/dam/document-library/installation-manuals/ac/split/rxl-g/RXL20-35G2V1B_3P232550-1_Installation%20manuals_French.pdf",
    "asn_senegal": "https://asn.sn/fr/node/1473",
}

# NF C 15-100, tableau 10-1f (section minimale cuivre, calibre maximal du disjoncteur, points maximum)
CIRCUITS = {
    "eclairage": {"nom": "Éclairage (points lumineux, prises commandées)", "section": 1.5, "disjoncteur": 16, "max_points": 8},
    "prises_8": {"nom": "Prises 16 A, 8 au plus", "section": 1.5, "disjoncteur": 16, "max_points": 8},
    "prises_12": {"nom": "Prises 16 A, 12 au plus", "section": 2.5, "disjoncteur": 20, "max_points": 12},
    "prises_cuisine": {"nom": "Prises de la cuisine / plan de travail, 6 au plus", "section": 2.5, "disjoncteur": 20, "max_points": 6},
    "specialise": {"nom": "Circuit spécialisé (lave-linge, lave-vaisselle, four, sèche-linge)", "section": 2.5, "disjoncteur": 20, "max_points": 1},
    "frigo": {"nom": "Réfrigérateur / congélateur (différentiel 30 mA à immunité renforcée)", "section": 2.5, "disjoncteur": 20, "max_points": 1},
    "plaque_mono": {"nom": "Plaque de cuisson / cuisinière en monophasé (sortie 32 A)", "section": 6.0, "disjoncteur": 32, "max_points": 1},
    "plaque_tri": {"nom": "Plaque de cuisson en triphasé (sortie 20 A)", "section": 2.5, "disjoncteur": 20, "max_points": 1},
    "chauffe_eau": {"nom": "Chauffe-eau électrique non instantané", "section": 2.5, "disjoncteur": 20, "max_points": 1},
    "volets": {"nom": "Volets roulants", "section": 1.5, "disjoncteur": 16, "max_points": None},
}
# « autres circuits » du même tableau (et bornes 32 A : 10 mm² / 40 A) : section → calibre maximal du disjoncteur
SECTION_MAX_A = {1.5: 16, 2.5: 20, 4.0: 25, 6.0: 32, 10.0: 40}
BREAKERS = (2, 10, 16, 20, 25, 32, 40)

COULEURS = ("Vert-jaune : TERRE uniquement (jamais une phase ni un neutre).",
            "Bleu : NEUTRE uniquement.",
            "Phase : toute autre couleur (rouge, marron, noir les plus courantes) ; une navette (retour de lampe) peut être d'une autre couleur.",
            "Installation ancienne ou modifiée : ne jamais se fier à la couleur seule, vérifier au détecteur de tension.")
DIFFERENTIELS = ("Tous les circuits sous interrupteur différentiel 30 mA ; au moins 2 interrupteurs différentiels 30 mA par logement.",
                 "Au moins 1 de type A : obligatoire pour la plaque de cuisson, le lave-linge et la recharge de véhicule.",
                 "8 circuits au plus par interrupteur différentiel ; 1 disjoncteur par circuit.",
                 "Climatiseur : Legrand le range avec le type F sur ligne dédiée ; suivre la notice du fabricant.")
CLIM_POSE = ("Circuit électrique dédié au tableau : disjoncteur selon la notice (souvent 16 à 32 A) sous différentiel 30 mA, jamais de "
             "rallonge ni de multiprise, jamais d'alimentation partagée avec un autre appareil.",
             "Liaison frigorifique : cuivre isolé, neuve, non écrasée ; longueur maximale selon le fabricant (souvent 20 à 30 m).",
             "Condensats : tuyau en pente descendante continue, passé sous la liaison frigorifique ; sinon l'eau déborde de l'unité intérieure.",
             "Mise en service : tirage au vide (purge de l'air) et fluide prescrit seulement (R32, R410A) ; pose par un professionnel.",
             "Unité extérieure : support solide, dégagements autour de l'appareil tels que la notice les donne.")
SECURITE = ("Avant de toucher : couper le disjoncteur général et vérifier l'absence de tension (détecteur, VAT). Une photo ne remplace pas "
            "les mesures (terre, isolement, test du différentiel) : un électricien qualifié intervient.")


class ElecError(ValueError):
    pass


def _pos(**vals) -> None:
    for name, v in vals.items():
        if v is None or not math.isfinite(float(v)) or float(v) <= 0:
            raise ElecError(f"{name} : nombre positif attendu.")


def courant(puissance_w: float, tension_v: float = U_MONO, cos_phi: float = 1.0) -> float:
    """I = P / (U × cos φ), monophasé."""
    _pos(puissance=puissance_w, tension=tension_v, cos_phi=cos_phi)
    return round(puissance_w / (tension_v * cos_phi), 2)


def chute_tension(courant_a: float, longueur_m: float, section_mm2: float, *, triphase: bool = False) -> dict:
    """ΔU = b × ρ × L × I / S (b = 2 en monophasé, √3 en triphasé), L = longueur du câble aller (m)."""
    _pos(courant=courant_a, longueur=longueur_m, section=section_mm2)
    b = math.sqrt(3) if triphase else 2.0
    du = b * RHO_CU * longueur_m * courant_a / section_mm2
    u = 400.0 if triphase else U_MONO
    return {"volts": round(du, 2), "pourcent": round(100 * du / u, 2),
            "formule": f"{'√3' if triphase else '2'} × {RHO_CU} × {longueur_m:g} m × {courant_a:g} A / {section_mm2:g} mm² = {du:.2f} V"}


def section_pour(courant_a: float, longueur_m: float | None = None, usage: str = "autre") -> dict:
    """Plus petite section du tableau dont le disjoncteur couvre le courant, puis section augmentée tant que la chute de tension dépasse
    la limite (3 % éclairage, 5 % autres)."""
    _pos(courant=courant_a)
    limit = DROP_LIMIT["eclairage" if usage == "eclairage" else "autre"]
    for s, max_a in SECTION_MAX_A.items():
        if max_a < courant_a:
            continue
        brk = next(b for b in BREAKERS if b >= courant_a)
        drop = chute_tension(courant_a, longueur_m, s) if longueur_m else None
        if drop and drop["pourcent"] > limit:
            continue
        return {"section_mm2": s, "disjoncteur_a": brk, "chute": drop, "limite_pourcent": limit,
                "regle": f"{s:g} mm² accepte un disjoncteur de {max_a} A au plus (NF C 15-100, tableau 10-1f)"}
    raise ElecError(f"{courant_a:g} A" + (f" sur {longueur_m:g} m" if longueur_m else "")
                    + " : au-delà du tableau des logements (10 mm² / 40 A), un électricien fait le calcul complet.")


def controle_circuit(usage: str, section_mm2: float, disjoncteur_a: float, points: int | None = None,
                     longueur_m: float | None = None, puissance_w: float | None = None) -> dict:
    """Un circuit décrit (lu sur une photo ou dit par le patron) comparé aux règles : danger, défaut ou conforme, avec la raison."""
    if usage not in CIRCUITS:
        raise ElecError(f"Usage inconnu : {usage}. Choix : {', '.join(CIRCUITS)}.")
    _pos(section=section_mm2, disjoncteur=disjoncteur_a)
    rule, out = CIRCUITS[usage], []
    max_a = SECTION_MAX_A.get(float(section_mm2))
    if max_a is not None and disjoncteur_a > max_a:
        out.append({"gravite": "danger", "constat": f"Disjoncteur {disjoncteur_a:g} A sur du {section_mm2:g} mm² (maximum {max_a} A) : "
                    "le câble peut chauffer sans que le disjoncteur coupe. Baisser le calibre ou passer à une section plus forte."})
    if section_mm2 < rule["section"]:
        out.append({"gravite": "danger", "constat": f"{rule['nom']} : section minimale {rule['section']:g} mm², ici {section_mm2:g} mm²."})
    if disjoncteur_a > rule["disjoncteur"]:
        out.append({"gravite": "defaut", "constat": f"{rule['nom']} : disjoncteur de {rule['disjoncteur']} A au plus, ici {disjoncteur_a:g} A."})
    if points and rule["max_points"] and points > rule["max_points"]:
        out.append({"gravite": "defaut", "constat": f"{points} points sur ce circuit : {rule['max_points']} au plus. Créer un circuit de plus."})
    drop = None
    if longueur_m and puissance_w:
        drop = chute_tension(courant(puissance_w), longueur_m, section_mm2)
        limit = DROP_LIMIT["eclairage" if usage == "eclairage" else "autre"]
        if drop["pourcent"] > limit:
            out.append({"gravite": "defaut", "constat": f"Chute de tension {drop['pourcent']:g} % (> {limit:g} %) : section trop faible pour cette longueur."})
    return {"circuit": rule["nom"], "conforme": not out, "constats": out or [{"gravite": "ok", "constat": "Conforme au tableau NF C 15-100."}],
            "chute": drop, "regle": rule, "source": SOURCES["nfc15100_tableau"], "securite": SECURITE}


def clim_puissance(surface_m2: float, hauteur_m: float = 2.5, *, forte_chaleur: bool = False) -> dict:
    """Puissance FROID conseillée : 100 W/m² (125 si logement ancien, sous toiture ou plein soleil) × hauteur / 2,50 m, puis la taille
    courante juste au-dessus. Repère simplifié : un bilan thermique fait foi. La puissance froid n'est pas la consommation électrique."""
    _pos(surface=surface_m2, hauteur=hauteur_m)
    w = surface_m2 * CLIM_W_M2[1 if forte_chaleur else 0] * hauteur_m / 2.5
    btu = w * BTU_PER_W
    size = next((s for s in CLIM_SIZES_BTU if s >= btu), None)
    return {"puissance_froid_w": round(w), "btu_h": round(btu),
            "taille_conseillee_btu": size, "taille_conseillee_kw": round(size / BTU_PER_W / 1000, 1) if size else None,
            "regle": f"{surface_m2:g} m² × {CLIM_W_M2[1 if forte_chaleur else 0]} W/m² × {hauteur_m:g} / 2,5 = {w:.0f} W ≈ {btu:.0f} BTU/h",
            "note": ("Plusieurs appareils ou une gainable : la pièce dépasse les splits courants." if size is None else
                     "Repère simplifié ; un bilan thermique (isolation, vitrages, occupants) fait foi."),
            "sources": [SOURCES["clim_100w"], SOURCES["clim_m2"]]}


def clim_alimentation(courant_a: float, longueur_m: float | None = None) -> dict:
    """Ligne dédiée d'un climatiseur depuis le courant de sa plaque signalétique (ou de la notice) : disjoncteur et section."""
    res = section_pour(courant_a, longueur_m)
    return {**res, "pose": CLIM_POSE, "note": "Le calibre exact est celui de la notice du fabricant ; ceci est le minimum compatible.",
            "sources": [SOURCES["nfc15100_tableau"], SOURCES["clim_notice"]]}


def regles() -> dict:
    return {"circuits": CIRCUITS, "section_disjoncteur_max": {f"{k:g} mm²": f"{v} A" for k, v in SECTION_MAX_A.items()},
            "couleurs": COULEURS, "differentiels": DIFFERENTIELS, "climatisation": CLIM_POSE, "securite": SECURITE,
            "chute_tension": "3 % éclairage, 5 % autres usages (depuis le compteur) ; ΔU = 2 × 0,0225 × L × I / S en monophasé.",
            "cadre": "Repères NF C 15-100 (à confirmer avec la norme sénégalaise ASN pour un chantier réel). UniC ne chiffre pas ces "
                     "travaux : conseil seulement.", "sources": SOURCES}
