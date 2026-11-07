# KukuFM PromoFinder

I use this app to find 20 to 60 second screenplay windows with a hook near the start and an unresolved ending. It returns timestamps and a review ranking. It does not edit video.

## Setup

I target Python 3.10 or newer and tested the pinned install on Python 3.12. Python 3.14 did not have a usable PyArrow wheel in my environment, so I used Python 3.12 there.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
if [ ! -f .env ]; then cp .env.example .env; fi
```

`make setup`, `make run`, `make app`, `make test`, `make verify`, and `make pdf` are shortcuts. `make pdf` builds the final PDF and refuses while the author sections below still have placeholders. `make draft-pdf` builds a draft.

I run the tests with `python -m pytest -q`. Most tests use a small synthetic script, so they also run when the confidential episode pack is not installed. The check for the original 50 episode pack is skipped when that pack is absent or a different show is installed.

I put the provider keys in `.env`. I can keep provider and model settings there, including `MODEL_NAME`, `MODEL_FALLBACK_NAME`, and `SECOND_MODEL_NAME`. The main model defaults to `openai/gpt-oss-120b`, the fallback is `openai/gpt-oss-20b`, and the comparison model is `qwen/qwen3.8-27b`. `GROQ_API_KEY2` and `GROQ_API_KEY3` are optional. If a Groq key reaches its daily token limit, the client tries the next configured key and records only the variable names, not the key values.

For another provider, I set `MODEL_PROVIDER` and its matching key. OpenAI compatible models use `OPENAI_COMPAT_BASE_URL` and `OPENAI_COMPAT_MODEL`. Anthropic models use `ANTHROPIC_MODEL`. The provider model field takes precedence over `MODEL_NAME`.

## Run on a show

I put episode text files in a folder and run:

```sh
python -m promofinder run --data ./data --output ./outputs
```

I can use `--heuristics-only` to run offline. `--resume` reuses cached model results. The CLI runs preflight before analysis. I can list provider models with `python -m promofinder models`.

The cache stores only response JSON, provider, model, and a prompt hash. It never writes prompts. The raw output folder stores model response JSON. The app can accept a ZIP, which is useful when running without a local data directory.

Before saving a response, the client checks it against the input text in memory. A response that repeats a ten-word screenplay passage stays in the local response cache for resume, but is omitted from raw output exports. The cache stores only the model response, provider, model, and prompt hash. The run report counts raw-output omissions.

## Outputs

`outputs/promos.json` and `promos.csv` contain ranked clips. `cut_sheet.csv` lists segments for an editor. Each promo has an EDL-style JSON file. `rejected.json` lists validation failures. Campaign plans are CSV and Markdown. `run_report.md` records run totals and errors. `raw_llm/` contains JSON responses. Outputs may contain short quoted screenplay evidence, so I keep the repository private until I review them.

## App hosting

I run the app locally with `streamlit run app.py`. The app is not hosted on Streamlit Community Cloud yet. To deploy it:

1. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) with an account that can access the private `elprofessor-15/KukuFM` GitHub repository.
2. Choose **Create app**, select repository `elprofessor-15/KukuFM`, branch `main`, and main file `app.py`.
3. In the app settings, add `GROQ_API_KEY`, `GROQ_API_KEY2`, `GROQ_API_KEY3`, and `APP_PASSWORD` to Secrets. Use the same key values from the local `.env`, do not put them in GitHub files.
4. Deploy. Streamlit will provide the live app URL in the app workspace. Test it in a private browser window. The app accepts an episode ZIP because the confidential local `data/` folder is not uploaded.

This deployment needs the account owner to complete the Streamlit sign-in and GitHub authorization. I cannot complete that step from this workspace.

## Ranking and feedback

The rank combines hook, cliffhanger, standalone, and cold-viewer scores with configured weights. It limits repeated episodes and hook types. I review each quote and boundary before using a clip. The feedback form saves accept or reject decisions locally. It does not train a model.

Each accept adds 0.5 points and each reject removes 0.5 points for promos with the same hook type. The adjustment is capped between minus one and plus one point.

## Limits

Screenplay time may not match the final video. Speaker aliases are not always resolved. An exact transcript quote does not prove that the visual moment reads clearly. A person should review all final cuts.

The live stability check sampled two candidates in five episodes, one candidate per request. It found top-10 overlap of 1.0 between `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`, and 1.0 on a live same-model repeat. The mean absolute score change was 0.233. This small sample does not measure every candidate in the show.

## Measured run and limits

The offline run parsed 50 episodes, generated 300 candidates, pruned 11,458 windows, ranked 30 promos, and rejected 39. It took 15.4 seconds. The selected promos passed the local duration, quote, and beat-edge checks. These checks do not prove that the clips work in video.

The first full live pass made 54 calls and used 132,015 input and 41,799 output tokens, 173,814 total, over 2,840.7 seconds. It failed at global ranking with a code error. A later live attempt hit Groq's daily token limit. I have not completed a full fresh live ranking or cold-viewer pass. The smoke-test quotes were accurate in 2 of 9 judgments. I do not have blind labels. Prices were set to zero, so the recorded cost is not an invoice or a useful price estimate.

The model API supports cached per-episode requests, but total usage still depends on episode count, prompt size, and provider limits. I keep an editor as the final check. Rerun the live pipeline after the provider quota resets, review the new report, and do not treat the current heuristic output as a finished AI ranking.
