# Drafting app — design

Side project. Keep it small.

## Goal

A Cursor-style document editor that uses a local LLM (Ministral 3 8B on vLLM) to rewrite selected text or a whole document, and records how long each edit takes so we can compare decoding **with** inference with reference (vLLM `ngram` speculation) and **without** it.

Success: upload a document, select text, ask for a change, see the diff, accept it, and later compare total seconds per mode on the same edits.

## Decisions

- Single user, no login. Plain text and Markdown only (`.txt`, `.md`, max 1 MB).
- vLLM runs on the GPU server in **one mode at a time**. Switching = stop the app, restart vLLM with `SPEC_METHOD=ngram` or `off` (`deploy/vllm/serve.sh`), start the app with the matching `SPEC_MODE`.
- The app runs locally with Docker Compose and reaches the vLLM server over its OpenAI-compatible API.
- The model always returns the **full document**; our code splices in only the highlighted part.
- Minimal error handling: basic input checks only. If the model server is down, the request fails.

## Architecture

```
Browser ──▶ api (FastAPI + static UI) ──S3──▶ minio
                 │
                 └─ LangChain ChatOpenAI ──HTTP──▶ vLLM :8001 (GPU server)
```

`docker-compose.yml` services:
- `api`: Python 3.12, FastAPI, LangChain (`langchain-openai`), `minio` client. Serves the API and the UI.
- `minio`: object storage with buckets `documents` and `runs`.

Configuration (env): `VLLM_BASE_URL` (default `http://host.docker.internal:8001/v1`), `VLLM_MODEL` (`drafting`), `SPEC_MODE` (`iwr` or `baseline`), MinIO endpoint and credentials.

## Storage (MinIO)

- `documents/{doc_id}/meta.json` — `{id, name, created_at, updated_at, version}`
- `documents/{doc_id}/v{n}.txt` — content of each version; `v1` is the upload, a new version on every accepted edit.
- `runs/{run_id}.json` — one record per edit (see Timing).

## Editing flow

1. **Open editor.** The app loads the latest version and sends one priming request (system prompt + document, `max_tokens=1`) so vLLM's prefix cache holds the document.
2. **Edit request.** `POST /api/documents/{id}/edit` with `{instruction, selection: {from, to} | null}`. `from`/`to` are character offsets used only inside our code; the model never sees them.
3. **Build the prompt.** If there is a selection, the document is sent with the selected text wrapped in place:

   ```
   <highlighted-text>
   ...selected text...
   </highlighted-text>
   ```

   System prompt rules: rewrite only the text inside `<highlighted-text>` following the instruction; return the complete document with the same tags around the new text; change nothing else; output only the document. With no selection there are no tags and the instruction applies to the whole document.
4. **Chain.** `ChatPromptTemplate | ChatOpenAI(base_url=VLLM_BASE_URL, temperature=0, max_tokens=8192) | StrOutputParser`. No tool-calling loop.
5. **Splice (our engine).**
   - Selection: take the text between the tags in the model output and replace only the original highlighted span with it. Everything outside comes from the original document, so nothing outside the selection can change. If the output does not contain exactly one tag pair, return an error and change nothing.
   - No selection: the model output is the new document.
6. **Response.** `{proposed_text, run}`; the UI shows a diff. **Accept** → `POST /api/documents/{id}/versions` with the text saves `v{n+1}`. **Reject** discards it.

## Timing and comparison

Each edit writes `runs/{run_id}.json`:

```json
{"id": "...", "doc_id": "...", "mode": "iwr", "instruction": "...",
 "has_selection": true, "seconds": 1.24, "output_tokens": 753,
 "tokens_per_second": 607.3, "key": "<sha256 of input document + selection + instruction>",
 "output_hash": "<sha256 of raw model output>", "created_at": "..."}
```

`seconds` is wall time of the model call only. `output_tokens` comes from the response usage. `key` matches the same edit across modes; `output_hash` shows whether both modes produced identical text.

`GET /api/runs/compare` groups runs by `key` and returns, per key, the latest IWR and baseline seconds, the speedup and whether outputs match, plus total seconds per mode over keys that have both.

## UI

Static HTML + vanilla JS served by FastAPI; CodeMirror 6 and its merge view from a CDN. No build step.

- **Documents** (`/`): upload form, list of documents → editor.
- **Editor** (`/editor/{id}`): CodeMirror with line numbers; instruction box and Run button; chip showing "Selection" or "Whole document"; after a run, a diff with Accept / Reject and a strip with mode, seconds, output tokens, tokens/s. Header shows `SPEC_MODE`.
- **Compare** (`/compare`): totals per mode and overall speedup, then a table of matched edits.

## Checks

- Upload: extension `.txt`/`.md`, size ≤ 1 MB, UTF-8.
- Edit: non-empty instruction; selection offsets inside the document.
- Splice: exactly one `<highlighted-text>` pair in the output.

## Testing

pytest unit tests for the highlight module: wrapping a selection, splicing a well-formed output, ignoring changes outside the tags, and rejecting missing or duplicated tags. Manual end-to-end check against the vLLM server in both modes.

## Layout

```
app/
  main.py          FastAPI routes + static/page serving
  config.py        env settings
  storage.py       MinIO documents and runs
  highlight.py     wrap selection, parse and splice output
  editor_chain.py  LangChain prompt + model call + timing
  static/          index.html, editor.html, compare.html, app.css, *.js
tests/test_highlight.py
Dockerfile
docker-compose.yml
requirements.txt
```

Out of scope: streaming, questions without edits, `.docx`/PDF, auth, handling model server failures.
