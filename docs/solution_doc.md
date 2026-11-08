# KukuFM PromoFinder solution

## Problem choice

I rank short, timestamped screenplay moments for promo review. I chose this because a useful result needs both a strong opening and a clear unresolved ending.

## Assumptions

See [ASSUMPTIONS.md](../ASSUMPTIONS.md). I assume screenplay timestamps align with the video timeline.

## How it works

Preflight -> parse and beats -> candidate windows -> score and review -> editor checks -> exports

Each file is parsed into timestamped blocks. Candidate 20 to 60 second windows are generated around hooks, revelations, and cliffhangers, then capped before ranking so an episode does not dominate the results. The optional Groq pass judges compact evidence, while deterministic code checks duration, beat boundaries, quote evidence, and overlap. The app presents ranked promos in an editor workflow and exports JSON, CSV, Markdown, and cut sheets.

## AI, code, and human review

Code parses and checks boundaries. An optional model judges compact candidate excerpts. A human editor decides whether the moment works in the final video.

## Scale, cost, and quality

The offline run parsed all 50 episodes in 15.4 seconds. It ranked 30 promos and rejected 39. The 30 selected promos passed duration, quote, and beat-snap checks. These are rule checks, not human quality scores.

The first live pass made 54 calls and used 132,015 input plus 41,799 output tokens, 173,814 total, in 2,840.7 seconds. It stopped at global ranking with a code error, so I do not treat that run as a finished AI ranking. I measured no provider cost because no prices were configured.

The three-episode smoke found exact quote evidence in 2 of 9 model judgments. JSON and timestamps were valid in 9 of 9. The raw proposal check found 12 valid proposals out of 300. I have not collected blind labels or cold-viewer results.

The five-episode stability sample found 1.0 top-10 overlap between `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`, and 1.0 overlap on a live repeat of the primary model. The same-model mean absolute score change was 0.233. This sample used two candidates per episode, so it is limited evidence.

## Failures

Rule-valid output does not guarantee viewer appeal. A weak candidate can pass every mechanical check while its opening relies on visual action that has no strong first-line hook, or while its ending is merely dramatic rather than unresolved.

The largest known failure was a full live ranking error at global ranking, recorded as an `UnboundLocalError` after the first live pass. The fallback pass and export path have since been tested offline.

The 30 output promos therefore include candidates that need human review. No blind-label study was completed in the submission window. The current quality threshold is conservative: every exported promo must pass duration, evidence, boundary, and overlap checks, but the editor decides cultural fit and social appeal.

## Tools and one AI mistake

I used Python, Streamlit, FastAPI, ReportLab, Pytest, Groq, GitHub, Vercel, and Streamlit Community Cloud. Groq was used for compact episode judgments and stability checks; deterministic Python handled parsing and validation. All AI output is judged against timestamps and screenplay text rather than accepted by display alone.

One observed model mistake was a Groq proposal that used valid JSON and accurate timestamps but changed the exact screenplay wording in its quote evidence. The quote verifier rejected that proposal. This showed why exact quote verification must stay in code outside the model.
