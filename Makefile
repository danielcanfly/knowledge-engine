.PHONY: install lint test compile ci build query clean

install:
	python3 -m venv .venv
	. .venv/bin/activate && python -m pip install --upgrade pip && python -m pip install -e '.[dev]'

lint:
	ruff check .

test:
	pytest -q

compile:
	python -m compileall -q src tests scripts

ci: lint test compile

build:
	OBJECT_STORE_BACKEND=filesystem FILESYSTEM_STORE_ROOT=.artifacts/store AUTH_MODE=disabled APP_ENV=development \
	knowledge-engine build --bundle examples/okf-bundle --channel staging --release-time 2026-07-02T12:00:00Z

query:
	OBJECT_STORE_BACKEND=filesystem FILESYSTEM_STORE_ROOT=.artifacts/store AUTH_MODE=disabled APP_ENV=development \
	knowledge-engine query --channel staging --query 'knowledge compiler' --audiences public,internal

clean:
	rm -rf .venv .pytest_cache .ruff_cache .artifacts .coverage htmlcov dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete
