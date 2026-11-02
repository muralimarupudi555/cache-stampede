# `make verify` is the gate and must pass on a clean clone with no network and no database.
#
# `make bench` runs the experiments and the transcript, which drive real threads against a
# real clock and take a couple of minutes. The transcript lives here rather than in the
# gate because its counts move slightly between runs, and a gate that leaves uncommitted
# changes behind is one people stop reading the output of.

PYTHON := python3

.PHONY: help install lint test verify bench tables cli clean

help:
	@echo "make install   install the package and its development dependencies"
	@echo "make verify    lint, tests, law check, number check - the gate"
	@echo "make bench     run the three experiments"

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest

tables:
	$(PYTHON) tools/render_tables.py

cli:
	$(PYTHON) tools/capture_cli.py

verify: lint test tables
	$(PYTHON) tools/check_laws.py
	$(PYTHON) tools/collect_metrics.py
	$(PYTHON) tools/check_numbers.py

bench: cli
	$(PYTHON) experiments/e1_the_stampede_factor.py
	$(PYTHON) experiments/e2_the_ttl_is_the_wrong_knob.py
	$(PYTHON) experiments/e3_what_the_fixes_do.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ *.egg-info
