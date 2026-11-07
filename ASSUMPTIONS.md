# Assumptions

- I assume screenplay timestamps match the source video's timeline. I need an editor to verify them against the final cut.
- I treat each parsed speaker label as its own canonical name unless punctuation and role words can be removed safely.
- A promo boundary must match a parsed beat boundary. I do not infer missing video frames.
- One-episode windows are the default. Cross-episode stitched promos remain experimental.
- The model scores candidate excerpts. Code checks their timestamps and exact quotes.
- Heuristic-only scores are a fallback, not human quality labels.
- I compare the two highest heuristic candidates from each of five episodes in the stability check. I request one candidate at a time to stay within the second model's observed output-token limit.
- Provider cost is zero unless per-token prices are configured.
- The app stores editor feedback in the selected output folder. It does not upload feedback elsewhere.
