PYTHON ?= python

.PHONY: router-deps router-setup

router-deps:
	$(PYTHON) -m pip install -r requirements-router.txt

# Run in the backend virtualenv. Never called by server startup or deployment.
router-setup: router-deps
	$(PYTHON) scripts/setup_automatic_routing.py
