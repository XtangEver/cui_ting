# Remove Redundant LLM Prompt Design

## Context

The Windows CLI production path calls
`VideoSummarizer._refine()` → `LLMProcessor.structured_refine()` and therefore
uses `STRUCTURED_REFINE_PROMPT`. `PROMPT_REFINE` is only referenced by the
otherwise unused compatibility method `LLMProcessor.refine()`. The two prompt
constants currently contain the same instructions, aside from trailing
whitespace.

## Design

- Keep `STRUCTURED_REFINE_PROMPT` as the single source of cleanup instructions.
- Remove `PROMPT_REFINE`.
- Keep the public `refine()` compatibility method, but have it format
  `STRUCTURED_REFINE_PROMPT` so existing external callers do not break.
- Update refined-cache prompt-echo detection to reference only the retained
  constant.
- Preserve the user's current prompt text byte-for-byte within the retained
  constant; this change only removes duplication.

## Verification

- Add a regression test proving both `refine()` and `structured_refine()` send
  the retained structured prompt and include the supplied text.
- Assert the removed constant no longer exists.
- Run the focused LLM/summarizer tests and the complete test suite.

## Non-goals

- No prompt wording changes.
- No changes to model selection, request parameters, retries, chunking, or LLM
  response cleanup.
