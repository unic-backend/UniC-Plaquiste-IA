from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    unic_env: str = "production"
    unic_data_dir: str = "./data"
    unic_host: str = "0.0.0.0"  # nosec B104 - serveur conteneurisé
    unic_port: int = 8000
    unic_public_url: str = ""

    # Code d'accès unique (app mono-propriétaire exposée sur Internet). Vide = pas de code (usage local).
    unic_access_code: str = ""
    unic_admin_email: str = "proprietaire@unic.local"
    unic_admin_name: str = "UniC Plaquiste"

    database_url: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Claude (Anthropic) — raisonnement profond, à la demande seulement
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"  # raisonnement profond
    anthropic_fast_model: str = "claude-sonnet-5-5"  # usage courant quand Claude est le seul moteur
    anthropic_voice_model: str = "claude-haiku-4-5-20251001"  # UniC vocal : conversation courante, la plus rapide (vide = modèle courant)
    anthropic_base_url: str = ""  # vide = adresse officielle du SDK
    web_search_enabled: bool = True  # recherche Internet par Claude (facturée à l'usage par Anthropic)
    web_search_max_uses: int = 3

    # Vibecode (https://vibecode.moe) — relais compatible Anthropic Messages, fournisseur SECONDAIRE.
    # Priorité : Anthropic officiel d'abord ; Vibecode n'est essayé que si Anthropic échoue (quota épuisé,
    # clé refusée, réseau/panne) ou n'est pas configuré. Même protocole (SDK anthropic), mêmes familles de modèles.
    # Doc officielle : https://vibecode.moe/setup/cc — ANTHROPIC_BASE_URL=https://vibecode.moe, clé « vk-… ».
    vibecode_enabled: bool = True  # false = Vibecode désactivé (coupe-circuit, Anthropic seul)
    vibecode_api_key: str = ""
    vibecode_base_url: str = "https://vibecode.moe"  # le SDK ajoute /v1 (ne PAS mettre de /v1 ici)
    vibecode_sonnet_model: str = "claude-sonnet-5-5"  # tâches quotidiennes (vérifié « online » sur vibecode.moe/models)
    vibecode_opus_model: str = "claude-opus-5-5"  # raisonnement complexe (vérifié « online » sur vibecode.moe/models)
    vibecode_haiku_model: str = "claude-haiku-4-5"  # voix rapide (vide = retombe sur le modèle Sonnet)
    vibecode_timeout_s: float = 180.0
    vibecode_max_retries: int = 2  # retries internes du SDK (429/5xx/connexion) avec backoff exponentiel

    # Refroidissement après un échec « quota »/« auth » d'Anthropic (secondes ; 0 = réessayer à chaque message) :
    # évite de marteler l'API officielle à chaque message quand son quota est épuisé, bascule directe sur Vibecode.
    ai_quota_cooldown_s: int = 300

    local_ai_url: str = ""
    local_ai_model: str = ""

    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    smtp_from: str = ""

    # Fiche Google (Business Profile API) — OAuth refresh token + identifiants de la fiche
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    gbp_account_id: str = ""
    gbp_location_id: str = ""

    # Coupe-circuit : LLM_ENABLED=false désactive tout appel IA ; l'appli continue en mode calcul/documents.
    llm_enabled: bool = True

    max_upload_mb: int = 250

    # CORS : origines autorisées (liste séparée par virgules). Vide = seulement l'origine du frontend servi.
    allowed_origins: str = ""

    # Redis (optionnel) : limite d'essais partagée. Vide = mémoire du processus.
    redis_url: str = ""

    @property
    def data_path(self) -> Path:
        p = Path(self.unic_data_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def storage_path(self) -> Path:
        p = self.data_path / "storage"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def artifacts_path(self) -> Path:
        p = self.storage_path / "artifacts"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_path(self) -> Path:
        p = self.storage_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def backups_path(self) -> Path:
        p = self.data_path / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_file = (self.data_path / "unic.db").as_posix()
        return f"sqlite:///{db_file}"

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")


settings = Settings()
