DB_TAG := 2026-27
PY := .venv/bin/python

db:  ## baixa o catálogo offline (valida o matcher sem depender da API)
	mkdir -p .cache
	curl -sL -o .cache/anime-db.json \
	  https://github.com/manami-project/anime-offline-database/releases/download/$(DB_TAG)/anime-offline-database-minified.json

test:
	$(PY) test_anilist.py
	$(PY) crunchyroll.py

.PHONY: db test
