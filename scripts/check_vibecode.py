"""Vérifie la configuration Vibecode AVANT de l'activer en production (modèles, endpoint, protocole).

Usage :
    cd backend && python ../scripts/check_vibecode.py              # liste les modèles (gratuit, 1 requête GET)
    cd backend && python ../scripts/check_vibecode.py --probe --yes  # sonde payante : 1 mini-complétion + streaming

Lit VIBECODE_API_KEY / VIBECODE_BASE_URL / VIBECODE_*_MODEL dans l'environnement ou dans backend/.env.
La clé n'est jamais affichée ni journalisée. --probe consomme quelques jetons chez Vibecode (quelques centimes max).
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def load_env(path: str) -> dict:
    """Variables d'un fichier .env (clé=valeur par ligne) — sans dépendance externe."""
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true", help="sonde payante : mini-complétion + streaming (quelques jetons)")
    ap.add_argument("--yes", action="store_true", help="confirme la sonde payante (sinon le script s'arrête)")
    args = ap.parse_args()

    env = load_env(os.path.join(os.getcwd(), ".env"))
    env = {**env, **os.environ}   # l'environnement gagne sur le fichier
    key = env.get("VIBECODE_API_KEY", "")
    base = (env.get("VIBECODE_BASE_URL", "https://vibecode.moe") or "https://vibecode.moe").rstrip("/")
    sonnet = env.get("VIBECODE_SONNET_MODEL", "claude-sonnet-5-5")
    opus = env.get("VIBECODE_OPUS_MODEL", "claude-opus-5-5")
    haiku = env.get("VIBECODE_HAIKU_MODEL", "claude-haiku-4-5")

    print(f"Endpoint : {base}  (le SDK ajoute /v1 — ne pas mettre de /v1 dans VIBECODE_BASE_URL)")
    if not key:
        print("VIBECODE_API_KEY absente : mets-la dans backend/.env (format vk-…) puis relance.")
        return 2
    print(f"Clé : présente ({key[:3]}…, jamais affichée) — {len(key)} caractères")

    import httpx

    # 1) Liste des modèles (GET /v1/models — gratuit)
    models = []
    with httpx.Client(timeout=30) as http:
        r = http.get(f"{base}/v1/models", headers={"x-api-key": key})
        if r.status_code == 401:   # certains relais lisent aussi Authorization: Bearer
            r = http.get(f"{base}/v1/models", headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            print(f"GET /v1/models → HTTP {r.status_code} : {r.text[:200]}")
            print("Vérifie VIBECODE_API_KEY et VIBECODE_BASE_URL (https://vibecode.moe, sans /v1).")
            return 1
        models = [m.get("id", "") for m in (r.json().get("data") or [])]
    print(f"\n{len(models)} modèle(s) disponible(s) sur le relais.")
    ok = True
    for label, mid in (("VIBECODE_SONNET_MODEL", sonnet), ("VIBECODE_OPUS_MODEL", opus), ("VIBECODE_HAIKU_MODEL", haiku)):
        if not mid:
            continue
        present = mid in models
        ok = ok and present
        print(f"  {'OK ' if present else 'ABSENT'}  {label} = {mid}")
    claude_models = sorted(m for m in models if m.startswith("claude-"))
    if claude_models:
        print("  Modèles Claude du relais : " + ", ".join(claude_models))

    # 2) Sonde payante (optionnelle) : protocole Messages, streaming, effort, déclaration d'outil
    if args.probe:
        if not args.yes:
            print("\n--probe consomme quelques jetons chez Vibecode. Relance avec --probe --yes pour confirmer.")
            return 0 if ok else 1
        import anthropic

        client = anthropic.Anthropic(api_key=key, base_url=base, timeout=60.0, max_retries=0)
        print(f"\nSonde payante sur {sonnet} (1 mini-complétion, max 32 jetons)…")
        resp = client.messages.create(model=sonnet, max_tokens=32,
                                      system="Réponds uniquement par le mot « OK ».",
                                      messages=[{"role": "user", "content": "test"}],
                                      output_config={"effort": "low"})
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        print(f"  create + output_config.effort : OK ({len(text)} caractère(s) en réponse)")
        with client.messages.stream(model=sonnet, max_tokens=32,
                                    messages=[{"role": "user", "content": "test"}]) as stream:
            streamed = "".join(ev.delta.text for ev in stream if getattr(ev, "type", "") == "content_block_delta"
                               and getattr(ev.delta, "type", "") == "text_delta")
        print(f"  streaming : OK ({len(streamed)} caractère(s) reçus en flux)")
        resp2 = client.messages.create(model=opus, max_tokens=16,
                                       tools=[{"name": "ping", "description": "test", "input_schema": {"type": "object"}}],
                                       messages=[{"role": "user", "content": "test"}])
        print(f"  déclaration d'outil sur {opus} : OK (stop_reason={resp2.stop_reason})")
        print("\nSonde terminée : le relais est compatible avec le fournisseur Vibecode d'UniC.")

    if not ok:
        print("\nUn modèle configuré est ABSENT du relais : corrige VIBECODE_*_MODEL dans .env "
              "(voir https://vibecode.moe/models) avant d'activer le relais.")
        return 1
    print("\nTous les modèles configurés sont disponibles. Le relais Vibecode est prêt (bascule automatique après Anthropic).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
