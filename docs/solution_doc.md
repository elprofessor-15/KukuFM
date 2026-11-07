# PromoFinder solution

## Problem choice

I rank short, timestamped screenplay moments for promo review. I chose this because a useful result needs both a strong opening and a clear unresolved ending.

## Assumptions

See [ASSUMPTIONS.md](../ASSUMPTIONS.md). I assume screenplay timestamps align with the video timeline.

## How it works

Preflight -> parse and beats -> candidate windows -> score and review -> editor checks -> exports

## AI, code, and human review

Code parses and checks boundaries. An optional model judges compact candidate excerpts. A human editor decides whether the moment works in the final video.

## Scale, cost, and quality

The offline run parsed all 50 episodes in 15.4 seconds. It ranked 30 promos and rejected 39. The 30 selected promos passed duration, quote, and beat-snap checks. These are rule checks, not human quality scores.

The first live pass made 54 calls and used 132,015 input plus 41,799 output tokens, 173,814 total, in 2,840.7 seconds. It stopped at global ranking with a code error, so I do not treat that run as a finished AI ranking. I measured no provider cost because no prices were configured.

My 3-episode smoke found exact quote evidence in 2 of 9 model judgments. JSON and timestamps were valid in 9 of 9. The raw proposal check found 12 valid proposals out of 300. I have not collected blind labels or cold-viewer results.

## Failures

[WRITE THIS YOURSELF: Review the real candidates in eval/failure_candidates.md and explain which picks are weak.]

## Tools and one AI mistake

[WRITE THIS YOURSELF: Record tools used and one observed model error from DEV_LOG.md or outputs/smoke_results.json.]
