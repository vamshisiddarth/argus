.PHONY: setup test lint fmt scan-aws scan-gcp scan-azure docs

setup:
	python -m venv .venv
	.venv/bin/pip install -r requirements.txt
	cp -n .env.example .env || true
	@echo "\nDone. Edit .env then run: make scan-aws"

test:
	pytest tests/ -v --tb=short

lint:
	ruff check .
	black --check .

fmt:
	black .
	ruff check --fix .

scan-aws:
	python main.py --cloud aws --run-now --dry-run

scan-gcp:
	python main.py --cloud gcp --run-now --dry-run

scan-azure:
	python main.py --cloud azure --run-now --dry-run

docs:
	mkdocs serve
