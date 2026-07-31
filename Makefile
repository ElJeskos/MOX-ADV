PYTHON ?= python3

.PHONY: check-okf check-okf-base check-okf-policy verify

check-okf: check-okf-base check-okf-policy

check-okf-base:
	$(PYTHON) scripts/check_okf.py okf

check-okf-policy:
	$(PYTHON) scripts/check_okf.py okf \
		--require-recommended-metadata \
		--require-trust-metadata \
		--require-index-metadata \
		--require project/source-authority.md \
		--require project/normative-prototype-specification.md \
		--require project/implementation-preconditions.md \
		--require references/initial-source-map.md \
		--require references/okf-v01-migration.md

verify: check-okf
