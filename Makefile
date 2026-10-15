.PHONY: dev test docker run-docker load
dev:
	./.venv/bin/uvicorn app.main:app --reload --port 8080
test:
	./.venv/bin/pytest
docker:
	docker build -t uae-einvoice-check .
run-docker:
	docker run --rm -p 8080:8080 -e WEB_CONCURRENCY=2 uae-einvoice-check
load:
	./.venv/bin/python scripts/loadtest.py http://127.0.0.1:8080
