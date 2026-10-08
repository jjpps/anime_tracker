PY := $(CURDIR)/.venv/bin/python
BACKEND := $(CURDIR)/backend

# glob em vez de lista: já esqueci de registrar arquivo de teste novo duas
# vezes, e o make passava verde ignorando a suíte inteira
test:
	@cd $(BACKEND) && for t in tests/test_*.py; do \
	  echo "== $$t"; $(PY) "$$t" || exit 1; \
	done
	@cd $(BACKEND) && $(PY) anime_tracker/crunchyroll.py

serve:
	cd $(BACKEND) && $(PY) -m anime_tracker serve

sync:
	cd $(BACKEND) && $(PY) -m anime_tracker crunchyroll $(ARGS)

novidades:
	cd $(BACKEND) && $(PY) -m anime_tracker novidades

.PHONY: test serve sync novidades
