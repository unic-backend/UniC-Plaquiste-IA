#!/usr/bin/env python3
"""Garde-fous du dépôt (voir AGENTS.md) : empêche un outil ou un agent de sortir de la base du projet ou de recréer ce qui existe.

Usage (CI, sur une pull request) :  python scripts/guardrails.py --base origin/main --labels "a,b"
Usage local :                        python scripts/guardrails.py --base origin/main
Le propriétaire met à jour la liste des fichiers essentiels avec :  python scripts/guardrails.py --update-manifest

Étiquette `core-change-approved` (posée par le propriétaire sur la pull request) : autorise zones protégées et suppressions.
Les règles de structure (dossier racine, second serveur, second package.json…) n'ont pas d'étiquette : le propriétaire modifie ce script.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVAL_LABEL = "core-change-approved"

# Zones protégées : seul le propriétaire les modifie (les mêmes que l'auto-réparation, plus les règles elles-mêmes).
PROTECTED = (
    "backend/app/auth.py", "backend/app/security.py", "backend/app/secrets_box.py", "backend/app/config.py",
    "backend/app/repair.py", "backend/app/selfcare.py", "backend/app/trust.py",
    ".github/", "Dockerfile", "render.yaml", "docker-compose.yml", "backend/requirements",
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursor/", ".windsurfrules", "ARCHITECTURE.md",
    "scripts/guardrails.py", "scripts/core_manifest.txt",
)
# Dossiers dont la suppression d'un fichier est refusée sans accord (la base du projet).
CORE_DIRS = ("backend/app/", "backend/tests/", "frontend/src/", "frontend/android/app/src/", "desktop/", "scripts/", "docs/")
ALLOWED_TOP_DIRS = {"backend", "frontend", "desktop", "docs", "scripts", ".github", ".cursor"}
SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|sk_live_[A-Za-z0-9]{20,}")
TEXT_EXT = (".py", ".ts", ".tsx", ".js", ".cjs", ".json", ".yml", ".yaml", ".md", ".java", ".xml", ".gradle", ".css", ".html", ".txt", ".toml", ".env")
MANIFEST = ROOT / "scripts" / "core_manifest.txt"


def _protected(path: str) -> bool:
    if path.startswith(".env") and path != ".env.example":   # .env réels protégés ; .env.example se documente à chaque nouveau réglage
        return True
    return any(path == p or path.startswith(p) for p in PROTECTED)


def check(changes: list[tuple[str, str]], labels: set[str], tree: list[str], read, manifest: list[str]) -> list[str]:
    """Rend la liste des violations (vide = tout va bien).

    changes : (statut git A/M/D/R, chemin) ; tree : fichiers suivis ; read(path) : texte d'un fichier ; manifest : fichiers essentiels.
    """
    out: list[str] = []
    approved = APPROVAL_LABEL in labels
    present = set(tree)

    for path in manifest:   # 1. la base est toujours là
        if path not in present:
            out.append(f"Fichier essentiel absent : {path} (supprimé ou renommé ?). Rien de ce qui a été bâti ne disparaît.")

    for status, path in changes:   # 2. zones protégées et suppressions
        if approved:
            break
        if _protected(path):
            out.append(f"Zone protégée modifiée : {path}. Réservée au propriétaire (étiquette « {APPROVAL_LABEL} » à poser par lui).")
        if status.startswith(("D", "R")) and path.startswith(CORE_DIRS):
            out.append(f"Fichier de la base supprimé ou déplacé : {path}. Interdit sans accord du propriétaire.")

    for path in tree:   # 3. structure : ne pas sortir de la base
        top = path.split("/", 1)[0]
        if "/" in path and top not in ALLOWED_TOP_DIRS:
            out.append(f"Nouveau dossier à la racine : {top}/ ({path}). Le projet garde ses dossiers : {', '.join(sorted(ALLOWED_TOP_DIRS))}.")
            break
    pkg = [p for p in tree if p.endswith("package.json") and not p.startswith(("frontend/", "desktop/"))]
    out += [f"Second projet Node : {p}. L'interface est dans frontend/, le bureau dans desktop/." for p in pkg]
    req = [p for p in tree if re.search(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|Pipfile|poetry\.lock)$", p) and not p.startswith("backend/")]
    out += [f"Second environnement Python : {p}. Le serveur vit dans backend/." for p in req]
    docker = [p for p in tree if re.search(r"(^|/)(Dockerfile[^/]*|docker-compose[^/]*\.ya?ml)$", p) and p not in ("Dockerfile", "docker-compose.yml")]
    out += [f"Second fichier de déploiement : {p}. Un seul Dockerfile et un seul docker-compose.yml existent." for p in docker]
    apps = [p for p in tree if p.endswith(".py") and not p.startswith(("backend/tests/", "scripts/")) and p != "backend/app/main.py"
            and "FastAPI(" in (read(p) or "")]
    out += [f"Second serveur FastAPI : {p}. Le serveur est backend/app/main.py ; ajoute des routes dans un routeur existant ou un nouveau routeur inclus par main.py." for p in apps]

    for _status, path in changes:   # 4. secrets (les tests contiennent de FAUSSES clés pour vérifier que l'IA les refuse : non scannés)
        if path.endswith(TEXT_EXT) and not path.startswith("backend/tests/") and SECRET_RE.search(read(path) or ""):
            out.append(f"Secret visible dans {path} : retire-le (tout passe par .env).")
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _changes(base: str) -> list[tuple[str, str]]:
    rows = []
    for line in _git("diff", "--name-status", "-M", f"{base}...HEAD").splitlines():
        parts = line.split("\t")
        if parts[0].startswith("R") and len(parts) == 3:
            rows += [("D", parts[1]), ("A", parts[2])]   # un renommage = la suppression de l'ancien chemin
        elif len(parts) >= 2:
            rows.append((parts[0], parts[-1]))
    return rows


def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _core_files(tree: list[str]) -> list[str]:
    keep = ("backend/app/", "backend/tests/", "frontend/src/", "frontend/android/app/src/main/java/", "desktop/main.cjs", "desktop/preload.cjs", "scripts/")
    top = ("AGENTS.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "README.md", "Dockerfile", "docker-compose.yml", "render.yaml", "Makefile",
           ".github/workflows/tests.yml", ".github/workflows/android.yml", ".github/workflows/desktop.yml", ".github/CODEOWNERS")
    return sorted(p for p in tree if p.startswith(keep) or p in top)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--labels", default="")
    ap.add_argument("--update-manifest", action="store_true")
    a = ap.parse_args()
    tree = [p for p in _git("ls-files").splitlines() if p]
    if a.update_manifest:
        MANIFEST.write_text("# Fichiers essentiels : ils ne disparaissent jamais (mis à jour par le propriétaire : scripts/guardrails.py --update-manifest)\n"
                            + "\n".join(_core_files(tree)) + "\n", encoding="utf-8")
        print(f"{len(_core_files(tree))} fichiers essentiels notés dans {MANIFEST.relative_to(ROOT)}")
        return 0
    manifest = [l.strip() for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] if MANIFEST.exists() else []
    if not manifest:
        print("scripts/core_manifest.txt absent ou vide : lance --update-manifest.")
        return 1
    labels = {l.strip() for l in a.labels.split(",") if l.strip()}
    problems = check(_changes(a.base), labels, tree, _read, manifest)
    if problems:
        print("GARDE-FOUS : la pull request enfreint les règles du dépôt (AGENTS.md) :\n")
        print("\n".join(f"  ✗ {p}" for p in problems))
        return 1
    print(f"Garde-fous : OK ({len(tree)} fichiers suivis, {len(manifest)} essentiels présents).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
