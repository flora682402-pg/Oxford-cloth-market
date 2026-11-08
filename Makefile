.PHONY: setup build preview serve test clean

PY ?= python3

setup:  ## Install build and test dependencies, plus the test browser
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m playwright install chromium

build:  ## Production site -> dist/
	$(PY) build.py

preview:  ## Claude preview build -> preview/
	$(PY) build.py --preview

serve: build  ## Serve dist/ like Cloudflare Pages at http://127.0.0.1:8000
	$(PY) tools/serve.py dist 8000

test:  ## Builds, JavaScript type check and the full test suite
	bash tests/run_all.sh

clean:
	rm -rf dist preview .pytest_cache tests/__pycache__ tools/__pycache__ __pycache__
