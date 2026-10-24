import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.main import app, get_llm, get_storage


class FakeStorage:
    def __init__(self):
        self.docs = {}
        self.runs = []

    def create_document(self, name, text):
        meta = {"id": uuid.uuid4().hex, "name": name, "created_at": "t",
                "updated_at": "t", "version": 1}
        self.docs[meta["id"]] = (meta, text)
        return meta

    def list_documents(self):
        return [meta for meta, _ in self.docs.values()]

    def get_document(self, doc_id):
        return self.docs[doc_id]

    def save_version(self, doc_id, text):
        meta, _ = self.docs[doc_id]
        meta = {**meta, "version": meta["version"] + 1}
        self.docs[doc_id] = (meta, text)
        return meta

    def save_run(self, run):
        self.runs.append(run)

    def list_runs(self):
        return list(self.runs)


@pytest.fixture
def client():
    storage = FakeStorage()
    llm = FakeListChatModel(responses=["A.\n<highlighted-text>b</highlighted-text>\n"])
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_llm] = lambda: llm
    yield TestClient(app), storage
    app.dependency_overrides.clear()


def test_upload_edit_and_accept(client):
    c, storage = client
    meta = c.post("/api/documents", files={"file": ("a.md", b"A.\nB.\n")}).json()
    resp = c.post(f"/api/documents/{meta['id']}/edit",
                  json={"instruction": "lowercase", "selection": {"from": 3, "to": 5}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["proposed_text"] == "A.\nb\n"
    assert len(storage.runs) == 1
    run = storage.runs[0]
    assert run["has_selection"] is True and run["doc_id"] == meta["id"]
    saved = c.post(f"/api/documents/{meta['id']}/versions", json={"text": body["proposed_text"]})
    assert saved.json()["version"] == 2
    assert c.get(f"/api/documents/{meta['id']}").json()["text"] == "A.\nb\n"


def test_empty_selection_key_matches_whole_document(client):
    c, storage = client
    meta = c.post("/api/documents", files={"file": ("a.md", b"A.\nB.\n")}).json()
    for selection in (None, {"from": 2, "to": 2}):
        c.post(f"/api/documents/{meta['id']}/edit",
               json={"instruction": "formal", "selection": selection})
    assert storage.runs[0]["key"] == storage.runs[1]["key"]
    assert storage.runs[0]["has_selection"] is False


def test_blank_instruction_is_rejected(client):
    c, _ = client
    meta = c.post("/api/documents", files={"file": ("a.md", b"A.\nB.\n")}).json()
    resp = c.post(f"/api/documents/{meta['id']}/edit", json={"instruction": "  ", "selection": None})
    assert resp.status_code == 400


def test_unreachable_model_returns_502(client):
    c, storage = client

    class DownLLM:
        def invoke(self, messages):
            import httpx, openai
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))

    app.dependency_overrides[get_llm] = lambda: DownLLM()
    meta = c.post("/api/documents", files={"file": ("a.md", b"A.\nB.\n")}).json()
    resp = c.post(f"/api/documents/{meta['id']}/edit", json={"instruction": "formal", "selection": None})
    assert resp.status_code == 502 and "vLLM server" in resp.json()["detail"]
    assert storage.runs == []


def test_bad_upload_is_rejected(client):
    c, _ = client
    resp = c.post("/api/documents", files={"file": ("a.pdf", b"x")})
    assert resp.status_code == 400 and "detail" in resp.json()
