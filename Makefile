.PHONY: setup test test-integration test-all lint fmt scan-aws scan-gcp scan-azure docs deploy-aws deploy-aws-multi

setup:
	python -m venv .venv
	.venv/bin/pip install -r requirements.txt
	cp -n .env.example .env || true
	@echo "\nDone. Edit .env then run: make scan-aws"

test:
	pytest tests/ -v --tb=short

test-integration:
	pytest tests/ -m integration -v --tb=short

test-all:
	pytest tests/ -m "" -v --tb=short

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

deploy-aws:
	cd deploy/aws/single-account && sam build && sam deploy --guided

deploy-aws-multi:
	cd deploy/aws/multi-account/hub && sam build && sam deploy --guided

docs:
	mkdocs serve
