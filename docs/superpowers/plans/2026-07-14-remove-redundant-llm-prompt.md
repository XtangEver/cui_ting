# Remove Redundant LLM Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain `STRUCTURED_REFINE_PROMPT` as the only cleanup prompt while preserving both public refinement entry points.

**Architecture:** The production `structured_refine()` path remains unchanged. The compatibility `refine()` method formats the same retained constant, and refined-cache prompt-echo detection references that constant once.

**Tech Stack:** Python 3.11, pytest, OpenAI-compatible client.

## Global Constraints

- Preserve the user's current `STRUCTURED_REFINE_PROMPT` text without wording changes.
- Do not change model selection, request parameters, retries, chunking, or response cleanup.
- Keep `LLMProcessor.refine(text: str, model_name: str) -> str` callable.

---

### Task 1: Consolidate the LLM cleanup prompt

**Files:**
- Modify: `tests/test_llm_processor.py`
- Modify: `core/llm_processor.py`
- Modify: `core/summarizer.py`

**Interfaces:**
- Consumes: `LLMProcessor.refine(text, model_name)` and `LLMProcessor.structured_refine(text, model_name)`.
- Produces: one class constant, `LLMProcessor.STRUCTURED_REFINE_PROMPT`, shared by both methods and cache validation.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_llm_processor.py`:

```python
def test_refine_entrypoints_share_only_structured_prompt(model_config, fake_client):
    processor = LLMProcessor(
        {"nanyan": model_config},
        client_factory=lambda **kwargs: fake_client,
    )

    processor.refine("input", "nanyan")
    processor.structured_refine("input", "nanyan")

    prompts = [
        request["messages"][0]["content"]
        for request in fake_client.chat.completions.requests
    ]
    assert prompts == [
        LLMProcessor.STRUCTURED_REFINE_PROMPT.format(text="input"),
        LLMProcessor.STRUCTURED_REFINE_PROMPT.format(text="input"),
    ]
    assert not hasattr(LLMProcessor, "PROMPT_REFINE")
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
conda run -n cui_ting python -m pytest tests/test_llm_processor.py::test_refine_entrypoints_share_only_structured_prompt -v
```

Expected: FAIL because `PROMPT_REFINE` still exists and `refine()` formats it.

- [ ] **Step 3: Apply the minimal production change**

In `core/llm_processor.py`, delete the `PROMPT_REFINE` constant and change:

```python
prompt = self.PROMPT_REFINE.format(text=text)
```

to:

```python
prompt = self.STRUCTURED_REFINE_PROMPT.format(text=text)
```

In `core/summarizer.py`, remove the `LLMProcessor.PROMPT_REFINE` entry from `prompt_markers`, retaining the `STRUCTURED_REFINE_PROMPT` marker.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
conda run -n cui_ting python -m pytest tests/test_llm_processor.py tests/test_summarizer.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 5: Run the complete verification suite**

Run:

```powershell
conda run -n cui_ting python -m pytest tests -q
conda run -n cui_ting python -m pip check
git diff --check
```

Expected: all tests PASS, no broken dependencies, and no whitespace errors.

- [ ] **Step 6: Commit only the reviewed implementation files**

```powershell
git add core/llm_processor.py core/summarizer.py tests/test_llm_processor.py
git commit -m "refactor: remove redundant LLM prompt"
```
