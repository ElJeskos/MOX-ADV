PYTHON ?= python3

.PHONY: check-okf verify

check-okf:
	$(PYTHON) scripts/check_okf.py okf \
		--require-index-metadata \
		--require-recommended-metadata \
		--require project/source-authority.md \
		--require project/normative-specification.md \
		--require references/initial-source-map.md

verify: check-okf
