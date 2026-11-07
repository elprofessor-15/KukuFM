# Submission checklist

- Name:
- Roll number:
- Branch:
- Problem chosen: KukuFM PromoFinder
- GitHub repository: https://github.com/elprofessor-15/KukuFM
- Streamlit app link: https://kukufm-gd3hvewryz.streamlit.app (Cloud app exists, first build failed with Python 3.14; select Python 3.12 and redeploy).
- Use repository `elprofessor-15/KukuFM`, branch `main`, and entry point `app.py`. Add `GROQ_API_KEY`, `GROQ_API_KEY2`, `GROQ_API_KEY3`, and `APP_PASSWORD` to Cloud Secrets.
- Fill in the failure and model-error sections in the solution document, then run `make pdf`.
- Record the walkthrough using `docs/walkthrough_script.md`.
- Put the PDF, video link, and raw run outputs from `outputs/` in the form.
- Label 12 promos in the Label tab and run `python eval/score.py`.
- Test every submitted link in a private browser window.
