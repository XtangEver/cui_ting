# Windows Release Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a privacy-hardened Windows CLI release to `origin/main` with annotated tag `windows-v1.0.0`.

**Architecture:** Build and test a sanitized release tree first, preserve the pre-rewrite tip on a local backup branch, then replace only the unpushed commit range with one release commit whose parent is the freshly fetched `origin/main`. Push the branch without force, verify it remotely, then push and verify the annotated tag.

**Tech Stack:** Git, PowerShell, Python 3.11, pytest, Conda environment `cui_ting`, GitHub remote `origin`.

## Global Constraints

- Never print API-key or Cookie values.
- Never force-push or rewrite a commit already present on `origin/main`.
- Preserve ignored `.env`, Cookie files, E2E artifacts, model files, and local outputs.
- Use annotated tag `windows-v1.0.0` exactly.
- Push `main` successfully and verify it before pushing the tag.
- The old remote history already contains `input_data.json`; remove it from the new release tree without rewriting the published old history.

---

### Task 1: Establish the remote and rollback baseline

**Files:**
- No tracked files changed.

**Interfaces:**
- Consumes: local `main`, `origin/main`, existing `v0.1.0` tag.
- Produces: a verified remote base SHA and a clean starting worktree.

- [ ] **Step 1: Verify branch, worktree, tag availability, and remote state**

```powershell
git status --short --branch
git fetch --prune origin
git merge-base --is-ancestor origin/main HEAD
git tag --list windows-v1.0.0
git ls-remote --exit-code --tags origin refs/tags/windows-v1.0.0
```

Expected: clean `release/windows-v1.0.0`; `origin/main` is an ancestor of
`HEAD`; the local and remote `windows-v1.0.0` tag checks return no existing
tag. Treat the expected `ls-remote --exit-code` status `2` as “tag absent”;
any other failure is a network/authentication blocker.

- [ ] **Step 2: Record the exact remote base and local tip without modifying refs**

```powershell
git rev-parse origin/main
git rev-parse HEAD
git rev-list --left-right --count origin/main...HEAD
```

Expected: zero commits on the remote-only side and one or more local-only
commits. Keep both SHAs in the execution report.

---

### Task 2: Add executable release-hygiene checks

**Files:**
- Create: `tests/test_release_hygiene.py`

**Interfaces:**
- Consumes: repository root, Git index, `.gitignore`, `README.md`, example files.
- Produces: automated assertions that the release tree excludes private runtime files and documents the Windows workflow.

- [ ] **Step 1: Write failing release-hygiene tests**

Create `tests/test_release_hygiene.py`:

```python
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def test_private_runtime_files_are_not_tracked():
    tracked = set(_git("ls-files").splitlines())
    forbidden = {
        ".env",
        "input_data.json",
        "cookie/bili_cookies.txt",
        "cookie/youtube_cookies.txt",
    }
    assert tracked.isdisjoint(forbidden)
    assert (ROOT / ".env.example").is_file()
    assert (ROOT / "input_data.example.json").is_file()


def test_private_runtime_paths_are_ignored():
    candidates = [
        ".env",
        ".env.local",
        "cookie/bili_cookies.txt",
        "cookie/nested/account.txt",
        "input_data.json",
        "test_case/task/source.mp3",
        ".e2e/run.log",
        "models/model.bin",
        "output/task/subtitle.zh.vtt",
        "private.pem",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        input="\n".join(candidates),
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(result.stdout.splitlines()) == set(candidates)
    assert subprocess.run(
        ["git", "check-ignore", "--no-index", ".env.example"], cwd=ROOT
    ).returncode != 0


def test_windows_readme_covers_the_supported_cli_workflow():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = [
        "## 快速开始",
        "## 隐私文件配置",
        "## 批量任务配置",
        "## 运行 CLI",
        "## 输出与断点恢复",
        "## 常见问题",
        "windows-v1.0.0",
    ]
    assert all(item in readme for item in required)
    assert not re.search(r"https?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?", readme)
```

- [ ] **Step 2: Run the new tests and verify RED**

```powershell
& 'C:\Users\t00855037\.conda\envs\cui_ting\python.exe' -m pytest tests/test_release_hygiene.py -v
```

Expected: FAIL because `input_data.json` is tracked, example files do not exist,
the ignore rules are incomplete, and the README headings are not yet present.

---

### Task 3: Build the sanitized Windows release tree

**Files:**
- Modify: `.gitignore`
- Rewrite: `README.md`
- Create: `.env.example`
- Create: `input_data.example.json`
- Remove from Git index only: `input_data.json`
- Modify: `docs/superpowers/specs/2026-07-13-windows-cli-long-audio-design.md`
- Modify: `docs/superpowers/plans/2026-07-13-windows-cli-long-audio.md`
- Modify: `tests/test_llm_processor.py`

**Interfaces:**
- Consumes: `config.yaml`, `requirements.txt`, `requirements-dev.txt`, CLI behavior, current prompt/model environment contract.
- Produces: a public README, safe examples, explicit ignore rules, and a final tree with no deployment-specific LLM values.

- [ ] **Step 1: Expand `.gitignore` with explicit private/runtime coverage**

Retain existing Python/IDE/OS rules and add these release rules without ignoring
the two example files:

```gitignore
.env
.env.*
!.env.example
cookie/*.txt
cookie/**/*.txt
input_data.json
test_case/
output/
.e2e/
.transcription_cache/
**/.transcription_cache/
**/.download_manifest.json
*.mp3
*.wav
*.m4a
*.webm
*.part
*.vtt
*.srt
models/
.cache/
*.pem
*.key
*.p12
*.pfx
```

- [ ] **Step 2: Create safe configuration examples**

Create `.env.example`:

```dotenv
NANYAN_API_KEY=<your-api-key>
NANYAN_BASE_URL=https://your-openai-compatible-endpoint.example/v1
NANYAN_MODEL=<your-model-name>
```

Create `input_data.example.json`:

```json
{
  "示例任务": "https://www.youtube.com/watch?v=VIDEO_ID",
  "另一个示例任务": "https://www.bilibili.com/video/BV_VIDEO_ID"
}
```

- [ ] **Step 3: Stop tracking the local task file without deleting it**

```powershell
git rm --cached -- input_data.json
Test-Path -LiteralPath input_data.json
```

Expected: Git stages deletion, while `Test-Path` returns `True`.

- [ ] **Step 4: Rewrite `README.md` for the Windows CLI release**

Write the following sections with commands and values verified against the
current tree:

```markdown
# cui_ting Windows CLI
## 功能与支持范围
## 快速开始
## 隐私文件配置
## 批量任务配置
## Windows 转录与 LLM 配置
## 运行 CLI
## 输出与断点恢复
## 常见问题
## 本地验证
## 发布版本
```

The guide must document Python 3.11, Conda environment `cui_ting`, FFmpeg and
FFprobe on `PATH`, model `medium`, CPU INT8, `D:\models`, 1,200/15-second audio
chunking, 128,000 LLM tokens, Cookie filenames, example-copy commands, exit
codes, cache recovery, and tag `windows-v1.0.0`. Use placeholders only.

- [ ] **Step 5: Remove deployment-specific values from tracked docs/tests**

Replace literal service endpoints with
`https://your-openai-compatible-endpoint.example/v1` and literal private model
identifiers with `example-model`. Keep environment variable names and public
behavior intact. Update assertions in `tests/test_llm_processor.py` to expect
`example-model`.

- [ ] **Step 6: Run hygiene tests and focused behavior tests for GREEN**

```powershell
& 'C:\Users\t00855037\.conda\envs\cui_ting\python.exe' -m pytest tests/test_release_hygiene.py tests/test_llm_processor.py -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit the reviewed sanitized tree before history reconstruction**

```powershell
git add .gitignore README.md .env.example input_data.example.json `
  docs/superpowers/specs/2026-07-13-windows-cli-long-audio-design.md `
  docs/superpowers/plans/2026-07-13-windows-cli-long-audio.md `
  tests/test_llm_processor.py tests/test_release_hygiene.py
git diff --cached --check
git commit -m "docs: prepare Windows CLI release"
```

Expected: only reviewed release files and the staged deletion of
`input_data.json` are committed; ignored local private files remain present.

---

### Task 4: Verify privacy and functionality before rewriting history

**Files:**
- No additional tracked files expected.

**Interfaces:**
- Consumes: the sanitized release tree from Task 3.
- Produces: test, dependency, tracked-path, content-scan, and ignored-file evidence.

- [ ] **Step 1: Run complete functional verification**

```powershell
& 'C:\Users\t00855037\.conda\envs\cui_ting\python.exe' -m pytest tests -q
& 'C:\Users\t00855037\.conda\envs\cui_ting\python.exe' -m pip check
& 'C:\Users\t00855037\.conda\envs\cui_ting\python.exe' -c "import cli; from core.transcriber import Transcriber; print('imports ok')"
git diff --check
git status --short --branch
```

Expected: all tests pass, dependencies/imports are valid, no whitespace errors,
and the tracked worktree is clean.

- [ ] **Step 2: Audit tracked path names**

```powershell
git ls-files
```

Programmatically reject tracked `.env`, Cookie text, `input_data.json`, E2E,
output, media, transcription cache, model, key, or credential paths. Report only
path names, never file contents.

- [ ] **Step 3: Audit tracked content and current `.env` values**

Scan the exact final tree for generic API keys, bearer tokens, private-key
headers, Netscape Cookie records, numeric HTTP endpoints, and deployment model
identifiers. Separately compare every nonempty `.env` value of length at least
eight with Git blobs; report variable names, counts, and paths only.

Expected: real API-key hit count is zero; no private credential or deployment
endpoint remains in the release tree. Public placeholders and test-only values
must be classified explicitly.

---

### Task 5: Replace only the unpushed history with one release commit

**Execution boundary:** Tasks 1–4 run on the isolated release branch. After
their task reviews pass, the controller fast-forward merges that branch into
local `main`. Before that fast-forward, the controller must move the primary
worktree's local `input_data.json` to a verified temporary ignored path. After
the merge, the controller must move it back unchanged and verify it remains
ignored and untracked. Tasks 5–6 then run serially from the primary `main`
worktree; subagents may audit evidence but must not mutate refs, create tags,
or push.

**Files:**
- Git refs and index only; final worktree content must not change.

**Interfaces:**
- Consumes: clean sanitized local tip and freshly fetched `origin/main`.
- Produces: local `main` exactly one commit ahead of `origin/main`, plus local rollback branch `backup/windows-v1.0.0-prepublish`.

- [ ] **Step 1: Fetch again and prove the remote base has not diverged**

```powershell
git fetch --prune origin
git merge-base --is-ancestor origin/main HEAD
git rev-list --left-right --count origin/main...HEAD
```

Expected: remote-only count is `0`. Stop if it is not.

- [ ] **Step 2: Create the rollback branch and record tree identity**

```powershell
git branch backup/windows-v1.0.0-prepublish HEAD
git rev-parse HEAD^{tree}
git rev-parse origin/main
```

Expected: backup branch points to the complete pre-rewrite history. Record the
tree SHA and remote base SHA.

- [ ] **Step 3: Reconstruct `main` as one release commit**

```powershell
$releaseTree = git rev-parse HEAD^{tree}
$remoteBase = git rev-parse origin/main
git reset --soft $remoteBase
git commit -m "feat: release Windows CLI v1.0.0"
git rev-parse HEAD^{tree}
```

Expected: the post-commit tree SHA equals `$releaseTree`; ignored private files
remain on disk and are absent from the index.

- [ ] **Step 4: Prove the rewritten branch is a normal fast-forward**

```powershell
git merge-base --is-ancestor origin/main main
git rev-list --left-right --count origin/main...main
git log --oneline origin/main..main
```

Expected: counts `0 1` and exactly one release commit. No force push is needed.

- [ ] **Step 5: Repeat full tests and push-range privacy scans**

Repeat Task 4 against `origin/main..main`, including comparison of the real
`.env` API key with every blob reachable from the single release commit.

Expected: all tests pass and every privacy scan is clean or classified as a
placeholder/test fixture.

---

### Task 6: Tag, push, and verify the Windows release

**Files:**
- Git annotated tag and remote refs only.

**Interfaces:**
- Consumes: verified clean release commit on local `main`.
- Produces: matching remote `main` and annotated tag `windows-v1.0.0`.

- [ ] **Step 1: Create the annotated tag locally**

```powershell
$release = git rev-parse HEAD
git tag -a windows-v1.0.0 -m "Windows CLI v1.0.0"
git rev-parse windows-v1.0.0^{}
```

Expected: peeled tag commit equals `$release`.

- [ ] **Step 2: Fetch one final time and push `main` without force**

```powershell
git fetch origin
git rev-parse HEAD^
git rev-parse origin/main
git push origin main:main
```

Expected: `HEAD^` equals the freshly fetched `origin/main`; normal push succeeds.

- [ ] **Step 3: Verify the remote branch before exposing the tag**

```powershell
git ls-remote origin refs/heads/main
```

Expected: remote branch SHA equals local `$release`.

- [ ] **Step 4: Push and verify the annotated tag**

```powershell
git push origin refs/tags/windows-v1.0.0
git ls-remote origin refs/tags/windows-v1.0.0 refs/tags/windows-v1.0.0^{}
```

Expected: the remote has both the annotated tag object and its peeled commit;
the peeled commit equals `$release`.

- [ ] **Step 5: Record final state**

```powershell
git status --short --branch
git log -1 --oneline --decorate
git tag -n1 --list windows-v1.0.0
```

Expected: clean `main`, synchronized with `origin/main`, and the release tag on
the release commit. Keep the local backup branch until the user explicitly asks
to remove it.
