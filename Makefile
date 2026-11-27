# TinyInsta 2026, campagne de mesures
.PHONY: figures install clean-figures

# regenere toutes les figures et tous les CSV de figures/ a partir de raw/
figures:
	python scripts/analyze.py

install:
	pip install -r bench/requirements.txt -r scripts/requirements.txt

clean-figures:
	rm -f figures/*.png figures/*.csv
