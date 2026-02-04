.PHONY: test lint fix install

install:
	pip install -r requirements_test.txt

test:
	pytest tests/ -vv

lint:
	ruff check custom_components tests
	ruff format --check custom_components tests

fix:
	ruff check --fix custom_components tests
	ruff format custom_components tests
