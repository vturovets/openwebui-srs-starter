.PHONY: lint test

lint:
	ruff check backend

test:
	pytest
	npm --prefix frontend test
