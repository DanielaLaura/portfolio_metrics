.PHONY: install extract load build pipeline review rebuild

install:        ## install Python dependencies
	pip install -r requirements.txt

extract:        ## run both extraction layers on data/pdfs (needs ANTHROPIC_API_KEY in .env)
	cd extract && python3 run_extraction.py

load:           ## stage committed CSVs into DuckDB (no API key needed)
	cd extract && python3 load_raw.py

build:          ## dbt seed + build all models + run tests
	cd dbt && dbt build --profiles-dir .

pipeline: extract build      ## full run: PDFs -> extraction -> warehouse -> marts

review: load build           ## reviewer path: rebuild from committed CSVs, show the pivot
	cd dbt && dbt show --profiles-dir . --select mart_metric_pivot --limit 40

rebuild:        ## full refresh: drop raw tables, reload CSVs, rebuild all models
	python3 -c "import duckdb; duckdb.connect('dbt/target/portfolio.duckdb').execute('drop schema if exists raw cascade')"
	cd extract && python3 load_raw.py
	cd dbt && dbt build --profiles-dir . --full-refresh
