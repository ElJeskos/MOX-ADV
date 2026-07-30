PYTHON ?= python3

.PHONY: check-modular-scope check-okf verify

check-modular-scope:
	$(PYTHON) scripts/validate_modular_scope.py

check-okf:
	$(PYTHON) scripts/check_okf.py okf \
		--require-index-metadata \
		--require-recommended-metadata \
		--require project/source-authority.md \
		--require project/normative-specification.md \
		--require references/initial-source-map.md

verify: check-modular-scope check-okf
