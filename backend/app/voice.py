"""Voix de lecture des réponses.

Deux moteurs côté appli : les voix du téléphone (gratuit, sans serveur) et les voix ElevenLabs (plus naturelles, et la TIENNE
si tu en enregistres une). Ce module gère ElevenLabs : clé chiffrée (secrets_box), liste des voix, clonage, synthèse.
Rien n'est envoyé à ElevenLabs sans clé saisie par le patron ; le clonage exige sa confirmation que c'est sa propre voix.
"""
from __future__ import annotations

import re

import httpx
from sqlalchemy.orm import Session

from app import secrets_box
from app.config import settings
from app.models import AppSetting

API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_multilingual_v2"   # français, wolof non garanti : voir limites dans la réponse de statut
MAX_CHARS = 2500                   # une réponse plus longue est coupée (coût et durée)
MAX_SAMPLE_BYTES = 10 * 1024 * 1024


class VoiceError(ValueError):
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


def api_key(db: Session) -> str:
    stored = _get(db, "elevenlabs_key")
    if stored:
        return secrets_box.decrypt(stored) or ""
    return getattr(settings, "elevenlabs_api_key", "") or ""


def _http(method: str, path: str, key: str, timeout: float = 60, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=timeout) as client:
            return client.request(method, API + path, headers={"xi-api-key": key}, **kw)
    except httpx.HTTPError:
        raise VoiceError("Impossible de joindre ElevenLabs depuis le serveur. Réessaie dans un instant.", 502)


def _explain(r: httpx.Response) -> VoiceError:
    try:
        d = r.json().get("detail")
        msg = d.get("message") if isinstance(d, dict) else str(d)
    except Exception:
        msg = ""
    msg = re.sub(r"\s+", " ", msg or "").strip()[:200]
    if r.status_code == 401:
        return VoiceError("Clé ElevenLabs refusée. Vérifie-la (elevenlabs.io → Profil → Clés API).", 400)
    if r.status_code == 402 or "paid" in msg.lower() or "subscription" in msg.lower():
        return VoiceError(f"Cette action demande un abonnement ElevenLabs payant. ({msg})", 402)
    if r.status_code == 429:
        return VoiceError("Quota ElevenLabs atteint. Réessaie plus tard ou change d'abonnement.", 429)
    return VoiceError(f"ElevenLabs a refusé la demande. {msg}".strip(), 502)


_SPACED_THOUSANDS = re.compile(r"(?<![\d,.])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?![\d])")
_SPEECH_UNITS = (
    (re.compile(r"(?<=\d)\s*(?:m²|m2)(?![\w])"), " mètres carrés"),
    (re.compile(r"(?<=\d)\s*ml(?![\w])"), " mètres linéaires"),
    (re.compile(r"(?<=\d)\s*mm(?![\w])"), " millimètres"),
    (re.compile(r"(?<=\d)\s*cm(?![\w])"), " centimètres"),
    (re.compile(r"(?<=\d)\s*m(?![\w²])"), " mètres"),
    (re.compile(r"(?<=\d)\s*kg(?![\w])"), " kilos"),
    (re.compile(r"(?<=\d)\s*[lL](?![\w'’])"), " litres"),
    (re.compile(r"(?<=\d)\s*h\s*(?=\d)"), " heures "),
    (re.compile(r"(?<=\d)\s*h(?![\w])"), " heures"),
)


def speech_numbers(t: str) -> str:
    """Montants et mesures dits comme un humain : « 1 250 000 FCFA » → « 1250000 francs CFA » (la voix lit « un million… »
    au lieu de « un, deux cent cinquante, zéro zéro zéro »), « 12 x 2,5 m » → « 12 par 2,5 mètres », « BA13 » → « B A 13 »."""
    t = _SPACED_THOUSANDS.sub(lambda m: re.sub(r"[ \u00a0\u202f]", "", m.group(0)), t)
    t = re.sub(r"(?<=\d)\s*[x×*]\s*(?=\d)", " par ", t)
    t = re.sub(r"\b(?:F\s?CFA|FCFA|XOF)\b", "francs CFA", t)
    t = re.sub(r"\bBA\s?(\d{2})\b", r"B A \1", t)
    t = re.sub(r"\bN[°o]\s?(?=\d)", "numéro ", t)
    for pattern, words in _SPEECH_UNITS:
        t = pattern.sub(words, t)
    return re.sub(r"\s*[→—–]\s*", ", ", t)


def clean_for_speech(text: str) -> str:
    """Texte lisible à voix haute : sans Markdown, tableaux, liens, ni liste de sources."""
    t = text.split("\n\n**Sources**")[0]
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"^\s*\|.*\|\s*$", " ", t, flags=re.M)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"[*_`>~]+", "", t)
    t = speech_numbers(t)
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\.{2,}", ".", t)
    return t.strip()


def status(db: Session) -> dict:
    key = api_key(db)
    return {
        "configured": bool(key),
        "voice_id": _get(db, "voice_selected"),
        "limits": "Voix ElevenLabs : français très bon ; wolof et langues africaines non garantis. Cloner ta voix demande un abonnement payant ElevenLabs.",
    }


def connect(db: Session, key: str) -> dict:
    key = (key or "").strip()
    if len(key) < 20 or re.search(r"\s", key):
        raise VoiceError("Clé invalide : colle la clé complète, sans espace.")
    r = _http("GET", "/voices", key)
    if r.status_code != 200:
        raise _explain(r)
    _put(db, "elevenlabs_key", secrets_box.encrypt(key))
    return status(db)


def disconnect(db: Session) -> dict:
    _put(db, "elevenlabs_key", "")
    _put(db, "voice_selected", "")
    return status(db)


def list_voices(db: Session) -> list[dict]:
    key = api_key(db)
    if not key:
        raise VoiceError("ElevenLabs n'est pas connecté.", 409)
    r = _http("GET", "/voices", key)
    if r.status_code != 200:
        raise _explain(r)
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        out.append({
            "id": v.get("voice_id"), "name": v.get("name"), "category": v.get("category"),
            "gender": labels.get("gender", ""), "accent": labels.get("accent", ""),
            "mine": v.get("category") in ("cloned", "generated", "professional"),
            "preview": v.get("preview_url") or "",
        })
    out.sort(key=lambda v: (not v["mine"], v["name"] or ""))
    return out


def select(db: Session, voice_id: str) -> dict:
    _put(db, "voice_selected", re.sub(r"[^A-Za-z0-9]", "", voice_id or "")[:40])
    return status(db)


def clone(db: Session, name: str, audio: bytes, filename: str, content_type: str, own_voice: bool) -> dict:
    if not own_voice:
        raise VoiceError("Confirme que c'est TA voix (ou celle d'une personne qui t'y autorise).")
    key = api_key(db)
    if not key:
        raise VoiceError("ElevenLabs n'est pas connecté.", 409)
    if len(audio) < 20_000:
        raise VoiceError("Enregistrement trop court. Parle au moins 30 secondes, au calme.")
    if len(audio) > MAX_SAMPLE_BYTES:
        raise VoiceError("Fichier trop gros (10 Mo maximum).")
    name = re.sub(r"\s+", " ", name or "").strip()[:40] or "Ma voix"
    r = _http("POST", "/voices/add", key, data={"name": name},
              files=[("files", (filename or "voix.webm", audio, content_type or "audio/webm"))])
    if r.status_code != 200:
        raise _explain(r)
    vid = r.json().get("voice_id", "")
    if not vid:
        raise VoiceError("ElevenLabs n'a pas renvoyé de voix.", 502)
    select(db, vid)
    return {"id": vid, "name": name}


def delete_voice(db: Session, voice_id: str) -> dict:
    key = api_key(db)
    if not key:
        raise VoiceError("ElevenLabs n'est pas connecté.", 409)
    voice_id = re.sub(r"[^A-Za-z0-9]", "", voice_id or "")
    r = _http("DELETE", f"/voices/{voice_id}", key)
    if r.status_code not in (200, 204):
        raise _explain(r)
    if _get(db, "voice_selected") == voice_id:
        _put(db, "voice_selected", "")
    return {"ok": True}


def speak(db: Session, text: str, voice_id: str = "") -> bytes:
    key = api_key(db)
    if not key:
        raise VoiceError("ElevenLabs n'est pas connecté.", 409)
    voice_id = re.sub(r"[^A-Za-z0-9]", "", voice_id or _get(db, "voice_selected") or "")
    if not voice_id:
        raise VoiceError("Aucune voix choisie.", 409)
    spoken = clean_for_speech(text)[:MAX_CHARS]
    if not spoken:
        raise VoiceError("Rien à lire dans ce message.")
    r = _http("POST", f"/text-to-speech/{voice_id}", key, params={"output_format": "mp3_44100_64"},
              json={"text": spoken, "model_id": MODEL})
    if r.status_code != 200:
        raise _explain(r)
    return r.content


STT_MODELS = ("scribe_v2", "scribe_v1")   # transcription ElevenLabs ; le plus récent d'abord
MAX_STT_BYTES = 200 * 1024 * 1024


def transcribe(db: Session | None, audio: bytes, filename: str = "son.mp3", key: str = "") -> dict:
    """Mots dits dans un son, avec leurs instants (sous-titres mot à mot du Studio vidéo) : clic du patron, ou automatique
    s'il l'a laissé activé. Langue détectée par ElevenLabs. Consomme du crédit ElevenLabs. `key` : clé déjà lue (appel hors de la base).
    Rend {"language": "fra", "words": [[début, fin, mot], …]}."""
    key = key or (api_key(db) if db is not None else "")
    if not key:
        raise VoiceError("ElevenLabs n'est pas connecté : ajoute ta clé dans Réglages → Voix pour créer des sous-titres.", 409)
    if not audio or len(audio) > MAX_STT_BYTES:
        raise VoiceError("Son vide ou trop long pour la transcription.", 413)
    r = None
    for model in STT_MODELS:
        r = _http("POST", "/speech-to-text", key, timeout=600, files={"file": (filename, audio, "audio/mpeg")},
                  data={"model_id": model, "timestamps_granularity": "word", "tag_audio_events": "false"})
        if r.status_code == 200 or r.status_code not in (400, 422) or "model" not in r.text.lower():
            break          # un modèle inconnu de ce compte : on essaie le suivant ; toute autre réponse est la bonne
    if r.status_code != 200:
        raise _explain(r)
    try:
        d = r.json()
    except ValueError:
        raise VoiceError("Réponse illisible d'ElevenLabs.", 502)
    words = []
    for w in d.get("words") or []:
        if not isinstance(w, dict) or w.get("type", "word") != "word":
            continue
        txt = re.sub(r"[\x00-\x1f\x7f<>]", "", str(w.get("text") or "")).strip()[:30]
        try:
            a, b = round(float(w.get("start")), 2), round(float(w.get("end")), 2)
        except (TypeError, ValueError):
            continue
        if txt and 0 <= a <= b:
            words.append([a, b, txt])
    return {"language": str(d.get("language_code") or "")[:8], "words": words}
