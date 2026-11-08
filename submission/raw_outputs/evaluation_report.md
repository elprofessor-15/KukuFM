# Evaluation report

- Run id: db77d1c1-0b08-4a76-a1b3-82728c0ee437
- Provider: mock
- Model: heuristics-only
- Parsed episodes: 50
- Ranked promos: 30
- Rejected promos: 39
- Input tokens: 0
- Output tokens: 0
- Initial full live pass tokens: 173814
- Initial full live pass stage issue: ["Global rank: UnboundLocalError: cannot access local variable 'rejected' where it is not associated with a value"]
- Current run tokens: 0
- Unsafe model responses omitted from raw outputs: 0
- Estimated cost: 0
- Runtime seconds: 15.4
- Initial live run stage error: ["Global rank: UnboundLocalError: cannot access local variable 'rejected' where it is not associated with a value"]
- Initial live run duration seconds: 2840.7
- Total measured tokens: 173814
- Mean measured tokens per episode: 3476.28
- Ten-show token projection at this run size: 1738140
- Blind label rows: 0
- Labels pending: fewer than 8 blind labels.
- Suspicious promos listed for review: 30

## Automated quality checks
- validity: 30/30 (1.000)
- quote_verification: 30/30 (1.000)
- duration_compliance: 30/30 (1.000)
- snap_rate: 30/30 (1.000)
- rejected_share: 39/69 (0.565)
- cold_viewer_conflict_missing: 0/0
- raw_proposal_validity: 12/300 (0.040)

## Three-episode model smoke
- openai/gpt-oss-120b: JSON 3/3, quotes 1/3, timestamps 3/3
- openai/gpt-oss-20b: JSON 3/3, quotes 0/3, timestamps 3/3
- qwen/qwen3.8-27b: JSON 3/3, quotes 1/3, timestamps 3/3

## Five-episode ablation
- heuristics: 6.05
- llm: 7.6
- hybrid: 7.9
- episodes: 5
- llm_windows_per_episode: 6
- method: Heuristics score every generated window. LLM and hybrid scores use the first six generated windows without heuristic ranking.

## Model stability
- primary_vs_second_model_top10_overlap: 1.0
- same_model_repeat_top10_overlap: 1.0
- same_model_score_variance: 0.0528
- same_model_mean_absolute_score_delta: 0.233
- episodes: 5
- primary_model: openai/gpt-oss-120b
- second_model: qwen/qwen3.8-27b
- candidates_per_episode: 2
- candidates_per_request: 1
- note: Single-candidate requests keep the second-model response within its observed output-token limit.
- same_model_repeat_cache_hits: 0
- same_model_live_repeat_calls: 12

I do not infer human quality from model scores. I use blind labels when available.
