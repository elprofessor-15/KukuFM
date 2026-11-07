.PHONY: setup run app test verify pdf draft-pdf
setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements-dev.txt
run:
	.venv/bin/python -m promofinder run
app:
	.venv/bin/streamlit run app.py
test:
	.venv/bin/python -m pytest -q
verify:
	.venv/bin/python scripts/verify_all.py
pdf:
	.venv/bin/python -m docs.build_pdf
draft-pdf:
	.venv/bin/python -m docs.build_pdf --draft --output docs/solution_doc_draft.pdf
