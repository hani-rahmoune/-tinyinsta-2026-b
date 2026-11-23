# TinyInsta 2026 — benchmark campaign
.PHONY: figures install clean-figures

## regenerate every CSV and PNG in figures/ from raw/ (the one command the subject asks for)
figures:
	python scripts/analyze.py

install:
	pip install -r bench/requirements.txt -r scripts/requirements.txt

clean-figures:
	rm -f figures/*.png figures/*.csv
