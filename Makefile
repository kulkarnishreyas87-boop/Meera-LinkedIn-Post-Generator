# Drafts-only LinkedIn assistant. `make dev` runs API+bot (:8000) and the Vite dashboard (:5173).
PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY = .venv/Scripts/python
endif

.PHONY: install dev api web build test import serve

install:
	uv venv --python 3.12 .venv || python3 -m venv .venv
	uv pip install --python .venv -e ".[dev]" || $(PY) -m pip install -e ".[dev]"
	cd web && npm install

dev:
	@echo "API + bot on http://127.0.0.1:8000  |  dashboard on http://localhost:5173"
	$(MAKE) -j2 api web

api:
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

web:
	cd web && npm run dev

build:
	cd web && npm run build

serve: build
	$(PY) -m app.cli serve

test:
	$(PY) -m pytest -q

import:
	$(PY) -m app.cli import $(or $(DIR),samples)
