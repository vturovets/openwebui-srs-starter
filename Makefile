.PHONY: lint test popularity-stats

lint:
	ruff check backend

test:
	pytest
	npm --prefix frontend test

popularity-stats:
	python -m scripts.build_popularity_stats --pretty
