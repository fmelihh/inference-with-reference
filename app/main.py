import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import openai
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from minio import Minio
from pydantic import BaseModel, ConfigDict, Field

from app.compare import compare_runs
from app.config import settings
from app.editor_chain import make_llm, prime, run_edit
from app.highlight import HighlightError, normalize_selection
from app.storage import Storage, decode_upload

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("uvicorn.error")


def _connect_storage(attempts: int = 30) -> Storage:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
    for i in range(attempts):
        try:
            return Storage(client)
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.storage = _connect_storage()
    app.state.llm = make_llm()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(openai.APIConnectionError)
async def model_unreachable(request: Request, exc: openai.APIConnectionError):
    return JSONResponse(
        status_code=502,
        content={"detail": f"Cannot reach the model at {settings.vllm_base_url}. Is the vLLM server running?"},
    )


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_llm(request: Request):
    return request.app.state.llm


class Selection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    start: int = Field(alias="from")
    end: int = Field(alias="to")


class EditRequest(BaseModel):
    instruction: str
    selection: Selection | None = None


class VersionRequest(BaseModel):
    text: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@app.get("/")
def index_page():
    return FileResponse(STATIC / "index.html")


@app.get("/editor/{doc_id}")
def editor_page(doc_id: str):
    return FileResponse(STATIC / "editor.html")


@app.get("/compare")
def compare_page():
    return FileResponse(STATIC / "compare.html")


@app.get("/api/config")
def get_config():
    return {"spec_mode": settings.spec_mode}


@app.post("/api/documents")
async def upload_document(file: UploadFile, storage=Depends(get_storage)):
    try:
        text = decode_upload(file.filename or "", await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return storage.create_document(file.filename, text)


@app.get("/api/documents")
def list_documents(storage=Depends(get_storage)):
    return storage.list_documents()


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, storage=Depends(get_storage)):
    meta, text = storage.get_document(doc_id)
    return {"meta": meta, "text": text}


@app.post("/api/documents/{doc_id}/prime")
def prime_document(doc_id: str, storage=Depends(get_storage), llm=Depends(get_llm)):
    _, text = storage.get_document(doc_id)
    prime(llm, text)
    return {"ok": True}


@app.post("/api/documents/{doc_id}/edit")
def edit_document(
    doc_id: str, req: EditRequest, storage=Depends(get_storage), llm=Depends(get_llm)
):
    instruction = req.instruction.strip()
    if not instruction:
        raise HTTPException(400, "Instruction must not be empty.")
    _, text = storage.get_document(doc_id)
    try:
        selection = normalize_selection(
            text, (req.selection.start, req.selection.end) if req.selection else None
        )
        result = run_edit(llm, text, instruction, selection)
    except HighlightError as e:
        if e.model_output is not None:
            log.warning("splice failed for doc %s, model output:\n%s", doc_id, e.model_output)
        raise HTTPException(400, str(e))
    span = f"{selection[0]}:{selection[1]}" if selection else "none"
    run = {
        "id": uuid.uuid4().hex,
        "doc_id": doc_id,
        "mode": settings.spec_mode,
        "instruction": instruction,
        "has_selection": selection is not None,
        "seconds": result.seconds,
        "output_tokens": result.output_tokens,
        "tokens_per_second": result.output_tokens / result.seconds if result.seconds else 0.0,
        "key": _sha256(text + "\0" + span + "\0" + instruction),
        "output_hash": _sha256(result.raw_output),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.save_run(run)
    return {"proposed_text": result.proposed_text, "run": run}


@app.post("/api/documents/{doc_id}/versions")
def save_version(doc_id: str, req: VersionRequest, storage=Depends(get_storage)):
    return storage.save_version(doc_id, req.text)


@app.get("/api/runs/compare")
def runs_compare(storage=Depends(get_storage)):
    return compare_runs(storage.list_runs())
