from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.models import CompanySettings, KnowledgeArticle, Material, Service, User
from app.security import hash_password


MATERIALS = [
    ("BA13-2500x1200", "Plaque de plâtre BA13 2500×1200", "plaques", "u", 0.08,
     "Référence catalogue standard. Dimensions 2,50 × 1,20 m. Prix UniC à saisir."),
    ("BA13-2500x1200-H", "Plaque BA13 hydrofuge 2500×1200", "plaques", "u", 0.08,
     "Usage pièces humides. Prix UniC à saisir."),
    ("BA13-2500x1200-F", "Plaque BA13 feu 2500×1200", "plaques", "u", 0.08,
     "Usage coupe-feu selon prescription. Prix UniC à saisir."),
    ("MONTANT-M48", "Montant M48", "ossature", "u", 0.05, "Ossature cloison. Prix UniC à saisir."),
    ("RAIL-R48", "Rail R48", "ossature", "ml", 0.05, "Rail haut/bas. Prix UniC à saisir."),
    ("MONTANT-M70", "Montant M70", "ossature", "u", 0.05, "Ossature cloison 70 mm. Prix UniC à saisir."),
    ("RAIL-R70", "Rail R70", "ossature", "ml", 0.05, "Rail 70 mm. Prix UniC à saisir."),
    ("VIS-PLAQUE", "Vis à plaque", "fixation", "u", 0.05, "Prix UniC à saisir."),
    ("BANDE-JOINT", "Bande à joint papier", "finition", "ml", 0.05, "Prix UniC à saisir."),
    ("ENDUIT-JOINT", "Enduit à joint", "finition", "kg", 0.10, "Prix UniC à saisir."),
    ("ENDUIT", "Enduit / plâtre (générique)", "finition", "kg", 0.10, "Produit à préciser. Prix UniC à saisir."),
    ("IMPRESSION", "Impression / primaire", "peinture", "L", 0.08, "Prix UniC à saisir."),
    ("PEINTURE", "Peinture (générique)", "peinture", "L", 0.08, "Produit à préciser. Prix UniC à saisir."),
    ("SUSPENTE", "Suspente de plafond", "plafond", "u", 0.05, "Prix UniC à saisir."),
    ("FOURRURE", "Fourrure / ossature plafond", "plafond", "ml", 0.05, "Prix UniC à saisir."),
    ("PORTE-ISO", "Porte isoplane (générique)", "portes", "u", 0.00, "Dimensions et gamme à préciser. Prix UniC à saisir."),
    ("POIGNEE", "Poignée / béquille", "portes", "u", 0.00, "Prix UniC à saisir."),
    ("SERRURE", "Serrure", "portes", "u", 0.00, "Prix UniC à saisir."),
]


SERVICES = [
    ("CLOISON", "Cloisons sèches / plaquisterie", "Pose de cloisons en plaques de plâtre sur ossature métallique.", "m²"),
    ("DOUBLAGE", "Doublage", "Doublage de murs existants.", "m²"),
    ("PLAFOND", "Faux plafonds", "Faux plafonds en plaques ou démontables.", "m²"),
    ("PLATRE", "Plâtrerie / enduits", "Enduits, lissage, plâtre.", "m²"),
    ("PEINTURE", "Peinture", "Impression et peinture de finition.", "m²"),
    ("PORTES", "Fourniture et pose de portes", "Portes, huisseries, quincaillerie.", "u"),
    ("FINITIONS", "Travaux de finition", "Finitions intérieures.", "ens"),
    ("POSE", "Pose / installation", "Pose sur chantier.", "ens"),
    ("DEMONTAGE", "Démontage / dépose", "Dépose de cloisons, plafonds, portes.", "ens"),
    ("CHANTIER", "Gestion de chantier", "Organisation, suivi, reporting.", "ens"),
]


ARTICLES = [
    (
        "services-unic",
        "Services UniC Plaquiste",
        "company",
        """UniC Plaquiste intervient exclusivement dans les métiers suivants (liste métier du système, à compléter par l'entreprise) :

- Construction
- Plaquisterie / cloisons sèches
- Cloisons
- Faux plafonds
- Plâtrerie
- Peinture
- Portes
- Travaux de finition
- Pose / installation
- Démontage
- Gestion de chantier
- Analyse de plans
- Métré / quantitatif
- Estimation matériaux
- Chiffrage / devis
- Facturation
- Bons de commande et de livraison
- Rapports de chantier

UniC AI ne doit jamais inventer un service hors de cette liste, ni un prix, ni une information client/fournisseur absente de la base.

Si une information n'est pas dans la base UniC : répondre « Je n'ai pas cette information dans la base UniC » puis demander la donnée.""",
    ),
    (
        "regle-donnees",
        "Règle absolue : ne jamais inventer les données métier",
        "procedure",
        """Interdit d'inventer :
- les prix
- les informations client
- les informations fournisseur
- les quantités non calculées
- les cotes non lues sur un document
- l'état des paiements
- les détails de projet
- les clauses de contrat
- les informations société

Statuts obligatoires : CONFIRMED / ESTIMATED / ASSUMED / MISSING.

Toute action sensible (envoi devis, facture, e-mail, publication, suppression, modification financière) exige une approbation humaine : BROUILLON → RELECTURE → APPROUVÉ → EXÉCUTÉ.""",
    ),
    (
        "methode-plaques",
        "Méthode de calcul des plaques de plâtre",
        "method",
        """Surface brute = longueur × hauteur × nombre de faces.
Surface nette = surface brute − (ouvertures × faces concernées).
Nombre de plaques = ⌈ surface nette × (1 + déchet) / (largeur plaque × hauteur plaque) ⌉.

Valeurs par défaut (HYPOTHÈSES, configurables dans Paramètres) :
- Plaque BA13 2,50 × 1,20 m = 3,00 m²
- Déchet 8 %
Ces valeurs ne sont pas des tarifs UniC.""",
    ),
    (
        "methode-ossature",
        "Méthode de calcul ossature métallique",
        "method",
        """Montants : n = ⌊ longueur / entraxe ⌋ + 1. Entraxe par défaut 0,60 m (hypothèse).
Rails : longueur × 2 (haut + bas).
Renforts d'ouverture non ajoutés automatiquement — à saisir si connus.
Vis : 15 / m² (hypothèse professionnelle).
Bande à joint : 1,40 m / m² (hypothèse).
Enduit à joint : 0,35 kg/m²/passe × 2 passes (hypothèse).""",
    ),
    (
        "approbation",
        "Procédure d'approbation des documents",
        "procedure",
        """Devis, factures, bons de commande, e-mails importants, publications :
1. L'IA prépare un brouillon.
2. L'utilisateur relit.
3. L'utilisateur approuve.
4. L'action est exécutée (PDF final, envoi si connecteur configuré).

Sans connecteur e-mail / réseaux / Google Business : l'envoi réel est NON DISPONIBLE. Le brouillon reste consultable et téléchargeable.""",
    ),
]


def seed_if_empty(db: Session) -> None:
    if db.query(User).first() is None:
        db.add(User(
            email=settings.unic_admin_email.lower(),
            name=settings.unic_admin_name,
            password_hash=hash_password(""),
            role="admin",
        ))
    if db.query(CompanySettings).first() is None:
        db.add(CompanySettings(name="UniC Plaquiste"))
    if db.query(Material).first() is None:
        for sku, name, cat, unit, waste, notes in MATERIALS:
            db.add(Material(sku=sku, name=name, category=cat, unit=unit,
                            waste_coefficient=waste, notes=notes, availability="unknown"))
    if db.query(Service).first() is None:
        for code, name, desc, unit in SERVICES:
            db.add(Service(code=code, name=name, description=desc, unit=unit,
                           selling_price=None, labor_rate=None,
                           notes="Prix / taux UniC non renseignés."))
    if db.query(KnowledgeArticle).first() is None:
        for slug, title, cat, body in ARTICLES:
            db.add(KnowledgeArticle(slug=slug, title=title, category=cat, body=body))
    db.commit()
    try:
        from app.metier import import_metier
        import_metier(db)
    except Exception:  # l'application doit démarrer ; l'erreur reste visible dans les logs
        logging.getLogger("unic.seed").exception("Import des connaissances métier impossible")
