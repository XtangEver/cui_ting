# Windows Release Publishing Design

## Objective

Publish the supported Windows CLI edition to `origin/main` under the annotated
tag `windows-v1.0.0`, with a user-oriented README and no local credentials,
cookies, task inputs, media, transcripts, model files, or deployment-specific
LLM values exposed by the commits being pushed.

## Current State and Risk

- Local `main` is ahead of `origin/main` by 24 commits.
- The real `NANYAN_API_KEY` from `.env` is absent from all reachable Git blobs.
- Deployment-specific LLM base URL and model-name values occur in unpushed
  design/plan history.
- `.env`, Cookie files, E2E files, and output directories are ignored and not
  tracked.
- `input_data.json` is already ignored but remains tracked, so its task URLs
  would be published unless it is removed from the index.

Because adding a later deletion commit does not remove data from older commits,
the release must sanitize the final tree and replace the 24 unpushed commits
with one clean release commit based on the current `origin/main` tip.

## Safety and Rollback

Before changing history:

1. Fetch `origin` and abort if `origin/main` has diverged from the locally known
   remote tip.
2. Create a local backup branch pointing to the pre-release local `main` tip.
3. Never force-push. The rewritten branch remains a fast-forward from the
   fetched `origin/main` because only commits that have never been pushed are
   replaced.
4. Keep ignored `.env`, Cookie files, test outputs, and models untouched.

The backup branch provides a local rollback reference until the remote branch
and tag have both been verified.

## README Structure

Rewrite `README.md` as the Windows CLI user's primary guide:

1. Supported scope and processing flow.
2. Hardware/software prerequisites and disk-location expectations.
3. Clone, Conda environment creation, dependency installation, and FFmpeg
   verification.
4. `.env.example` setup for an OpenAI-compatible LLM, including transcription-
   only mode.
5. Cookie placement and privacy warning.
6. `input_data.example.json` copy/edit workflow for batch tasks.
7. `config.yaml` reference for medium/CPU/INT8, `D:\models`, 1,200-second
   chunks, 15-second context, output paths, and LLM token limit.
8. CLI commands, exit codes, outputs, cache/recovery behavior, and common
   troubleshooting.
9. A release privacy checklist and local test commands.

The README must contain placeholders only—no real API key, endpoint, Cookie,
task URL, or private model identifier.

## Privacy Controls

Update `.gitignore` with explicit coverage for:

- `.env` and `.env.*`, while allowing tracked `.env.example`.
- `cookie/*.txt` and nested Cookie text files.
- `input_data.json`, output/test directories, E2E evidence, logs, and
  transcription/download caches.
- Downloaded media/subtitles and partial files (`mp3`, `wav`, `m4a`, `webm`,
  `part`, `vtt`, `srt`).
- Local model/cache directories and common private-key/credential file types.

Create:

- `.env.example` with placeholder `NANYAN_API_KEY`, `NANYAN_BASE_URL`, and
  `NANYAN_MODEL` values.
- `input_data.example.json` containing non-sensitive example URLs.

Remove `input_data.json` from Git tracking without deleting the user's local
file. Sanitize release documentation/tests so deployment-specific LLM endpoint
and model values do not enter the rewritten release commit.

## History Reconstruction

After the final tree is sanitized and verified:

1. Preserve the current tip on a local backup branch.
2. Reconstruct local `main` as one Windows release commit whose parent is the
   fetched `origin/main` tip and whose tree is the reviewed sanitized tree.
3. Confirm `git merge-base --is-ancestor origin/main main` succeeds and the
   ahead/behind count is exactly `0/N`, never requiring a force push.

## Verification Gates

Before creating the tag or pushing:

- Run the complete pytest suite in Conda environment `cui_ting`.
- Run `pip check`, import smoke checks, and `git diff --check`.
- Confirm all documented setup commands and example-file names match the tree.
- Confirm `git ls-files` contains no `.env`, Cookie text, `input_data.json`,
  E2E/output/cache/media, key, or credential files.
- Compare the real `.env` API key against every blob reachable from the exact
  commits to be pushed; output only counts and paths.
- Scan the push range for generic API-key, bearer-token, private-key, Cookie,
  and deployment-endpoint patterns, reviewing every match without printing
  secret values.
- Confirm the worktree is clean and the release commit is a fast-forward of
  `origin/main`.

## Tag and Push Sequence

1. Create annotated tag `windows-v1.0.0` on the verified release commit.
2. Push local `main` to `origin/main` without force.
3. Verify the remote branch resolves to the local release commit.
4. Push `windows-v1.0.0` explicitly.
5. Verify the remote tag resolves to the same commit and retains its annotated
   tag object/message.

If branch push fails, do not push the tag. If tag push fails after the branch
push succeeds, keep the local tag and retry only the tag after diagnosing the
failure.

## Non-goals

- No GitHub Release asset bundle or installer is created in this task.
- No Web/A/B runtime support is restored.
- No production API key, Cookie, or model binary is uploaded.
- No force push or rewrite of already-published remote history is allowed.
