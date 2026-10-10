import os

# Les tests tournent hors production : sans code d'accès, le serveur de production refuse l'API (voir main.access_code_guard).
os.environ.setdefault("UNIC_ENV", "development")
