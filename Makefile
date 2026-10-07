.PHONY: dev test lint up down build

dev:       ## Serveur de développement (http://localhost:8000)
	cd backend && UNIC_ENV=development uvicorn app.main:app --reload --port 8000

test:      ## Tests serveur
	cd backend && UNIC_DATA_DIR=$$(mktemp -d) python -m pytest -q

lint:      ## Ruff + Bandit (comme la CI)
	ruff check backend/app --select F,E9
	bandit -q -r backend/app -ll

build:     ## Image Docker
	docker compose build

up:        ## Démarre l'appli (+ Redis et HTTPS avec : make up PROFILE=prod)
	docker compose $(if $(PROFILE),--profile $(PROFILE)) up -d --build

down:
	docker compose --profile prod down
