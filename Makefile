.PHONY: all pipeline eda report clean

all: pipeline eda

# Fetch Bulbapedia + TCGCSV, extract, link and merge prices -> search/*.json
pipeline:
	uv run main.py

# Statistics and figures used in the report -> eda/stats.json, report/figures/*.pdf
eda:
	uv run eda/characterize.py

# Needs a LaTeX installation with the acmart class (or upload report/ to Overleaf)
report:
	cd report && latexmk -pdf main.tex

clean:
	cd report && latexmk -C main.tex
