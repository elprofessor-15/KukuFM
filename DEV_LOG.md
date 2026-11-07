# Development log

I will record observed bugs and model behavior here.

The first dependency install failed under the machine's Python 3.14 because Streamlit's PyArrow dependency had no compatible wheel and tried to build without CMake. I switched the project environment to Python 3.12, then the pinned install completed.

The first smoke-test launch failed because Python used the scripts folder as its import path. I added the project root to the script import path before retrying.

The first live smoke attempt returned validation errors because the JSON schema was not included in the request prompt. I added the schema to the request and reran all three models. The corrected run produced valid JSON and timestamps for all nine samples, but exact quote accuracy was low. The Qwen smoke calls hit output-token-per-minute limits, so the client recorded the provider messages and honored the retry delay.

The corrected smoke response headers reported 1000 requests per minute and 8000 tokens per minute for each model. Qwen also reported a 1000 output-token-per-minute limit and a request of 1252 output tokens. A separate 429 asked to retry after 51 seconds. I kept the main model settings at 20 requests per minute and 5000 tokens per minute in `.env`, below its observed header limits.

## Model smoke test

- openai/gpt-oss-120b, episode 1: JSON valid True, quote accurate True, timestamp accurate True.
- openai/gpt-oss-120b, episode 2: JSON valid True, quote accurate False, timestamp accurate True.
- openai/gpt-oss-120b, episode 3: JSON valid True, quote accurate False, timestamp accurate True.
- openai/gpt-oss-20b, episode 1: JSON valid True, quote accurate False, timestamp accurate True.
- openai/gpt-oss-20b, episode 2: JSON valid True, quote accurate False, timestamp accurate True.
- openai/gpt-oss-20b, episode 3: JSON valid True, quote accurate False, timestamp accurate True.
- qwen/qwen3.8-27b, episode 1: JSON valid True, quote accurate True, timestamp accurate True.
- qwen/qwen3.8-27b, episode 2: JSON valid True, quote accurate False, timestamp accurate True.
- qwen/qwen3.8-27b, episode 3: JSON valid True, quote accurate False, timestamp accurate True.

Observed rate limits: {"openai/gpt-oss-120b": {"request_limit": "1000", "token_limit": "8000", "retry_after_seconds": []}, "openai/gpt-oss-20b": {"request_limit": "1000", "token_limit": "8000", "retry_after_seconds": []}, "qwen/qwen3.8-27b": {"request_limit": "1000", "token_limit": "8000", "retry_after_seconds": ["51"]}}
Observed 429 messages: [{"model": "qwen/qwen3.8-27b", "status": 429, "message": "{\"error\":{\"message\":\"Request too large for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): Limit 1000, Requested 1252. The request's expected output toke", "headers": {"x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-requests": "995", "x-ratelimit-remaining-tokens": "8000", "x-ratelimit-reset-requests": "7m12s", "x-ratelimit-reset-tokens": "1ms"}}, {"model": "qwen/qwen3.8-27b", "status": 429, "message": "{\"error\":{\"message\":\"Request too large for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): Limit 1000, Requested 1252. The request's expected output toke", "headers": {"x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-requests": "993", "x-ratelimit-remaining-tokens": "5554", "x-ratelimit-reset-requests": "10m4.8s", "x-ratelimit-reset-tokens": "18.345s"}}, {"model": "qwen/qwen3.8-27b", "status": 429, "message": "{\"error\":{\"message\":\"Rate limit reached for model `qwen/qwen3.8-27b` on output tokens per minute (OTPM): Limit 1000, Used 920, Requested 914. Please try again in 50.0", "headers": {"retry-after": "51", "x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-requests": "993", "x-ratelimit-remaining-tokens": "5784", "x-ratelimit-reset-requests": "10m4.8s", "x-ratelimit-reset-tokens": "16.62s"}}]

The first 50 episode live run parsed all episodes but its global ranking stage stopped with an `UnboundLocalError` before finishing later stages. I fixed the rejection-list initialization and started a new full run so the final exports include that stage.

The leak check found that a small number of model responses repeated screenplay text outside the final short quote evidence. I added an in-memory ten-word shingle check. Responses that match the input stay in the local cache for resume but are omitted from raw outputs, and matching model explanations are replaced with a short review note. I removed the already generated raw files that failed this check.

After I included output-token headroom in the rate limiter, the first bible prompt no longer fit the configured token budget. I reduced the bible chunk size so its prompt leaves space for the schema and expected output, then added a test for that limit.

A later real request showed the main Groq model's daily token cap: 200,000 tokens, with 196,853 used and 3,248 requested. The API returned retry-after values of 44 and 151 seconds on two requests. A fallback-model request completed, but the quota prevented a verified full live run. I added detection for the provider's "tokens per day" 429 response so the pipeline stops cleanly instead of retrying it as a transient error.
