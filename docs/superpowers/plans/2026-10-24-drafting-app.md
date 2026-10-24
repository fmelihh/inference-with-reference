# Drafting App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A small Cursor-style editor that rewrites highlighted text (or a whole document) with Ministral 3 8B on vLLM and records edit timings so IWR and baseline runs can be compared.

**Architecture:** One FastAPI service serves a static HTML/JS UI and a JSON API, stores documents and run records in MinIO, and calls vLLM through a one-step LangChain chain. Our code wraps the selection in `<highlighted-text>` tags and splices only the tagged part of the model output back into the original.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, langchain-core, langchain-openai, minio (Python client), pytest, Docker Compose, MinIO, CodeMirror 6 from a CDN.

**Spec:** `docs/superpowers/specs/2026-10-24-drafting-app-design.md`

## Global Constraints

- Side project: minimal error handling, basic checks only; no handling for model server failures.
- Uploads: `.txt` or `.md`, ≤ 1 MB (1_048_576 bytes), UTF-8.
- Tag text exactly `<highlighted-text>` and `</highlighted-text>`.
- Model call: `temperature=0`, `max_tokens=8192`, model name from `VLLM_MODEL` (default `drafting`), base URL from `VLLM_BASE_URL` (default `http://host.docker.internal:8001/v1`).
- `SPEC_MODE` is `iwr` or `baseline`, set at app start.
- MinIO buckets `documents` and `runs`; object layout exactly as in the spec.
- No IPs, usernames or server paths in tracked files (repo will be public).

## Review Focus

1. Model adds a newline just inside the tags (`<highlighted-text>\nnew\n</highlighted-text>`) when the selection had none → splice drops that one added leading/trailing newline. Test in Task 1.
2. Document already contains the literal tag text → edit is rejected before calling the model. Test in Task 1.
3. Whole-document mode output wrapped in a Markdown code fence → one outer ```` ``` ```` fence is stripped. Test in Task 1.
4. Upload with Windows line endings → `\r\n` normalized to `\n` so offsets from the editor match the stored text. Test in Task 2.
5. Empty selection (`from == to`) → treated as whole-document edit. Test in Task 1.

---

### Task 1: Highlight engine

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `app/__init__.py`, `app/highlight.py`
- Test: `tests/test_highlight.py`

**Interfaces:**
- Produces:
  - `OPEN_TAG = "<highlighted-text>"`, `CLOSE_TAG = "</highlighted-text>"`
  - `class HighlightError(ValueError)`
  - `normalize_selection(text: str, selection: tuple[int, int] | None) -> tuple[int, int] | None` — `None` for no/empty selection; raises `HighlightError` if out of range.
  - `wrap(text: str, start: int, end: int) -> str` — `text[:start] + OPEN_TAG + text[start:end] + CLOSE_TAG + text[end:]`; raises `HighlightError` if `text` already contains either tag.
  - `splice(original: str, start: int, end: int, model_output: str) -> str` — replacement = the text between the single tag pair in `model_output`; result = `original[:start] + replacement + original[end:]`.
  - `clean_full_output(model_output: str) -> str` — strips one outer code fence if present.

- [ ] **Step 1: Create `requirements.txt`**: `fastapi`, `uvicorn[standard]`, `python-multipart`, `langchain-core`, `langchain-openai`, `minio`, `pytest`, `httpx` (pin current versions). `pytest.ini` with `pythonpath = .` and `testpaths = tests`.

- [ ] **Step 2: Write failing tests** in `tests/test_highlight.py`:

```python
from app.highlight import wrap, splice, clean_full_output, normalize_selection, HighlightError
import pytest

DOC = "Line one.\nThe main reason is long.\nLine three.\n"
S, E = DOC.index("The main"), DOC.index("Line three") - 1  # selection = second line, no newline

def test_wrap_inserts_tags_in_place():
    assert wrap(DOC, S, E) == "Line one.\n<highlighted-text>The main reason is long.</highlighted-text>\nLine three.\n"

def test_splice_replaces_only_selection():
    out = "Line one.\n<highlighted-text>Short reason.</highlighted-text>\nLine three.\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"

def test_splice_ignores_changes_outside_tags():
    out = "LINE ONE CHANGED\n<highlighted-text>Short reason.</highlighted-text>\nextra\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"

def test_splice_drops_newlines_model_added_inside_tags():
    out = "Line one.\n<highlighted-text>\nShort reason.\n</highlighted-text>\nLine three.\n"
    assert splice(DOC, S, E, out) == "Line one.\nShort reason.\nLine three.\n"

@pytest.mark.parametrize("out", ["no tags here", "<highlighted-text>a</highlighted-text><highlighted-text>b</highlighted-text>", "<highlighted-text>never closed"])
def test_splice_rejects_missing_or_duplicate_tags(out):
    with pytest.raises(HighlightError):
        splice(DOC, S, E, out)

def test_wrap_rejects_document_containing_tag():
    with pytest.raises(HighlightError):
        wrap("has <highlighted-text> inside", 0, 3)

def test_clean_full_output_strips_one_code_fence():
    assert clean_full_output("```markdown\nNew doc\n```") == "New doc\n"
    assert clean_full_output("New doc\n") == "New doc\n"

def test_normalize_selection():
    assert normalize_selection(DOC, None) is None
    assert normalize_selection(DOC, (5, 5)) is None
    assert normalize_selection(DOC, (S, E)) == (S, E)
    with pytest.raises(HighlightError):
        normalize_selection(DOC, (0, len(DOC) + 1))
```

- [ ] **Step 3: Run** `pytest tests/test_highlight.py -v` → FAIL (module not found).

- [ ] **Step 4: Implement `app/highlight.py`** with the interfaces above. Newline rule in `splice`: strip one leading `\n` from the replacement if the original selection does not start with `\n`, and one trailing `\n` if it does not end with `\n`. Exactly one `OPEN_TAG` and one `CLOSE_TAG`, open before close, else `HighlightError("model did not return exactly one highlighted section")`.

- [ ] **Step 5: Run** `pytest -v` → all PASS.

- [ ] **Step 6: Commit** `feat: add highlight wrap/splice engine`.

### Task 2: Settings, MinIO storage and run comparison

**Files:**
- Create: `app/config.py`, `app/storage.py`, `app/compare.py`
- Test: `tests/test_storage.py`, `tests/test_compare.py`

**Interfaces:**
- Produces:
  - `app/config.py`: `settings` object with `vllm_base_url`, `vllm_model`, `spec_mode`, `minio_endpoint` (default `minio:9000`), `minio_access_key`, `minio_secret_key`, read from env (plain `os.environ.get`, no extra dependency).
  - `app/storage.py`:
    - `MAX_UPLOAD_BYTES = 1_048_576`
    - `decode_upload(filename: str, data: bytes) -> str` — checks extension `.txt`/`.md`, size, UTF-8; returns text with `\r\n` → `\n`; raises `ValueError` with a user-facing message.
    - `class Storage` with `__init__(self, client: Minio)` (creates buckets `documents`, `runs` if missing), `create_document(name: str, text: str) -> dict`, `list_documents() -> list[dict]` (newest `updated_at` first), `get_document(doc_id: str) -> tuple[dict, str]`, `save_version(doc_id: str, text: str) -> dict`, `save_run(run: dict) -> None`, `list_runs() -> list[dict]`.
    - Meta dict: `{"id", "name", "created_at", "updated_at", "version"}`; ids are `uuid4().hex`; times ISO-8601 UTC.
  - `app/compare.py`: `compare_runs(runs: list[dict]) -> dict` returning `{"rows": [...], "totals": {"iwr": float, "baseline": float, "speedup": float | None}}`. Each row: `{"key", "instruction", "iwr_seconds", "baseline_seconds", "speedup", "identical"}` using the latest run per (key, mode); `speedup = baseline / iwr`; totals only over keys with both modes.

- [ ] **Step 1: Write failing tests.** `tests/test_storage.py` tests only `decode_upload`:

```python
def test_decode_upload_normalizes_crlf():
    assert decode_upload("a.md", b"one\r\ntwo\r\n") == "one\ntwo\n"

@pytest.mark.parametrize("name,data", [("a.pdf", b"x"), ("a.txt", b"\xff\xfe\x00"), ("a.txt", b"x" * (1_048_576 + 1))])
def test_decode_upload_rejects(name, data):
    with pytest.raises(ValueError):
        decode_upload(name, data)
```

`tests/test_compare.py`: two keys; key A has iwr 1.0 s and baseline 3.0 s with equal `output_hash`, key B has only iwr 2.0 s. Assert row A `speedup == 3.0` and `identical is True`, row B `baseline_seconds is None`, and `totals == {"iwr": 1.0, "baseline": 3.0, "speedup": 3.0}`. Add a second, newer iwr run for key A with 0.5 s and assert the row uses 0.5.

- [ ] **Step 2: Run** `pytest -v` → new tests FAIL.

- [ ] **Step 3: Implement** the three modules. `Storage` stores JSON with `put_object` and `io.BytesIO`; `list_documents` reads every `*/meta.json` under `documents`.

- [ ] **Step 4: Run** `pytest -v` → all PASS.

- [ ] **Step 5: Commit** `feat: add settings, MinIO storage and run comparison`.

### Task 3: Editor chain

**Files:**
- Create: `app/editor_chain.py`
- Test: `tests/test_editor_chain.py`

**Interfaces:**
- Consumes: `wrap`, `splice`, `clean_full_output`, `normalize_selection` (Task 1); `settings` (Task 2).
- Produces:
  - `SYSTEM_PROMPT: str` — rules from the spec: rewrite only the text inside `<highlighted-text>` following the instruction; if there are no tags, apply the instruction to the whole document; return the complete document, keeping the tags around the rewritten text; change nothing else; output only the document, no explanations or code fences. Document appended after the rules.
  - `build_messages(document: str, instruction: str, selection: tuple[int, int] | None) -> list[BaseMessage]` — `[SystemMessage(SYSTEM_PROMPT + "\n\n" + document_or_wrapped), HumanMessage(instruction)]`.
  - `@dataclass EditResult: proposed_text: str; raw_output: str; seconds: float; output_tokens: int`
  - `make_llm() -> ChatOpenAI` (base_url, model, `api_key="none"`, temperature 0, max_tokens 8192).
  - `run_edit(llm, document: str, instruction: str, selection: tuple[int, int] | None) -> EditResult` — times only `llm.invoke(...)` with `time.perf_counter()`; tokens from `response.usage_metadata["output_tokens"]`; proposed text via `splice` or `clean_full_output`.
  - `prime(llm, document: str) -> None` — invoke with the unwrapped document and `max_tokens=1` (`llm.bind(max_tokens=1)`).

- [ ] **Step 1: Write failing tests**:

```python
def test_build_messages_wraps_selection():
    msgs = build_messages("A.\nB.\n", "shorter", (3, 5))
    assert "<highlighted-text>B.</highlighted-text>" in msgs[0].content
    assert msgs[1].content == "shorter"

def test_build_messages_whole_document_has_no_tags():
    msgs = build_messages("A.\nB.\n", "formal", None)
    assert "<highlighted-text>" not in msgs[0].content.split(SYSTEM_PROMPT)[1]

def test_run_edit_splices_with_fake_model():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    llm = FakeListChatModel(responses=["A.\n<highlighted-text>b</highlighted-text>\n"])
    result = run_edit(llm, "A.\nB.\n", "lowercase", (3, 5))
    assert result.proposed_text == "A.\nb\n" and result.seconds >= 0
```

`run_edit` must treat missing `usage_metadata` (the fake model) as `0` output tokens.

- [ ] **Step 2: Run** `pytest tests/test_editor_chain.py -v` → FAIL.
- [ ] **Step 3: Implement** `app/editor_chain.py`.
- [ ] **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: Commit** `feat: add LangChain editor chain with timing`.

### Task 4: API, UI and Docker

**Files:**
- Create: `app/main.py`, `app/static/index.html`, `app/static/editor.html`, `app/static/compare.html`, `app/static/app.css`, `app/static/editor.js`, `Dockerfile`, `docker-compose.yml`, `.env.example`
- Modify: `README.md` (how to run)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces routes:
  - Pages: `GET /` → index.html, `GET /editor/{doc_id}` → editor.html, `GET /compare` → compare.html. Static files at `/static`.
  - `GET /api/config` → `{"spec_mode": ...}`
  - `POST /api/documents` (multipart `file`) → meta; 400 with `{"detail": msg}` on `ValueError`.
  - `GET /api/documents` → list of meta.
  - `GET /api/documents/{id}` → `{"meta", "text"}`
  - `POST /api/documents/{id}/prime` → `{"ok": true}`
  - `POST /api/documents/{id}/edit` body `{"instruction": str, "selection": {"from": int, "to": int} | null}` → `{"proposed_text", "run"}`; 400 on empty instruction or `HighlightError`. Writes the run record from the spec (`key` = sha256 of `text + "\0" + f"{start}:{end}" + "\0" + instruction`, `output_hash` = sha256 of raw output).
  - `POST /api/documents/{id}/versions` body `{"text": str}` → meta.
  - `GET /api/runs/compare` → `compare_runs(storage.list_runs())`.
- App wiring: `storage` and `llm` created in a FastAPI `lifespan`; tests override with `app.dependency_overrides` or by setting module-level objects, implementer's choice.

- [ ] **Step 1: Write failing API test** `tests/test_api.py` using `TestClient`, an in-memory fake `Storage` (same methods, dict-backed) and `FakeListChatModel`: upload `a.md`, edit with a selection, assert `proposed_text` has the replacement and one run was saved; assert `POST .../edit` with `"instruction": "  "` returns 400.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** `app/main.py`. **Step 4: Run** `pytest -v` → all PASS.
- [ ] **Step 5: UI.** Plain HTML + one CSS file; pages fetch the JSON API.
  - `index.html`: upload form, document list linking to `/editor/{id}`.
  - `editor.html` + `editor.js` (ES module): load CodeMirror 6 (`codemirror`, `@codemirror/merge`) from `https://esm.sh` pinned versions; on load fetch the document, call `/prime`; editor with line numbers; chip shows "Selection" when `state.selection.main` is non-empty else "Whole document"; Run sends offsets from the main selection, converted from CodeMirror's UTF-16 positions to Python code-point offsets (`[...doc.sliceString(0, pos)].length`) so emoji and other astral characters don't shift the splice; result shows a `MergeView` (original vs proposed) with Accept (POST versions, reload) and Reject; strip shows mode, seconds, output tokens, tokens/s; header shows `spec_mode`.
  - `compare.html`: totals and a table from `/api/runs/compare`.
- [ ] **Step 6: Docker.** `Dockerfile` (python:3.12-slim, install requirements, `uvicorn app.main:app --host 0.0.0.0 --port 8080`). `docker-compose.yml`: `minio` (`minio/minio` pinned, `server /data --console-address :9001`, ports 9000/9001, volume), `api` (build `.`, port 8080, `env_file: .env`, `extra_hosts: ["host.docker.internal:host-gateway"]`, depends_on minio). `.env.example` with every setting, `SPEC_MODE=iwr`, placeholder MinIO credentials. `.env` is git-ignored.
- [ ] **Step 7: README** "Run the app": `cp .env.example .env`, `docker compose up --build`, open `http://localhost:8080`; switching modes procedure from the spec.
- [ ] **Step 8: Commit** `feat: add API, editor UI and docker compose`.

### Task 5: End-to-end check

- [ ] **Step 1:** Start the vLLM server and `docker compose up --build`. Expected: `http://localhost:8080` lists no documents, `/api/config` returns `{"spec_mode": "iwr"}`.
- [ ] **Step 2:** Upload a ~40-line `.md`, open the editor, select one paragraph, ask "make this shorter", Run. Expected: diff shows only that paragraph changed; strip shows seconds and tokens/s.
- [ ] **Step 3:** Run a whole-document instruction ("make the tone more formal"). Expected: a full-document diff.
- [ ] **Step 4:** Restart vLLM with `SPEC_METHOD=off`, restart the app with `SPEC_MODE=baseline`, repeat Steps 2–3 with identical selections and instructions. Expected: `/compare` shows both modes per edit, a speedup and `identical` for each.
- [ ] **Step 5:** Restore vLLM to `ngram`. Commit any fixes.
