DB_TAG := 2026-27
PY := $(CURDIR)/.venv/bin/python
BACKEND := $(CURDIR)/backend

db:  ## baixa o catálogo local do AniList (casa temporadas sem a API)
	mkdir -p .cache
	curl -sL -o .cache/anime-db.json \
	  https://github.com/manami-project/anime-offline-database/releases/download/$(DB_TAG)/anime-offline-database-minified.json

test:
	cd $(BACKEND) && $(PY) tests/test_anilist.py
	cd $(BACKEND) && $(PY) tests/test_config.py
	cd $(BACKEND) && $(PY) tests/test_db.py
	cd $(BACKEND) && $(PY) tests/test_server.py
	cd $(BACKEND) && $(PY) tests/test_sync.py
	cd $(BACKEND) && $(PY) anime_tracker/crunchyroll.py

serve:
	cd $(BACKEND) && $(PY) -m anime_tracker serve

sync:
	cd $(BACKEND) && $(PY) -m anime_tracker sync

match:
	cd $(BACKEND) && $(PY) -m anime_tracker match $(ARGS)

.PHONY: db test sync match serve
