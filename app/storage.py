import io
import json
import uuid
from datetime import datetime, timezone

from minio import Minio

MAX_UPLOAD_BYTES = 1_048_576
DOCS = "documents"
RUNS = "runs"


def decode_upload(filename: str, data: bytes) -> str:
    if not filename.lower().endswith((".txt", ".md")):
        raise ValueError("Only .txt and .md files are supported.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("File is too large (limit 1 MB).")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File is not valid UTF-8 text.") from None
    return text.replace("\r\n", "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, client: Minio):
        self.client = client
        for bucket in (DOCS, RUNS):
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)

    def _put(self, bucket: str, name: str, body: bytes, content_type: str) -> None:
        self.client.put_object(
            bucket, name, io.BytesIO(body), len(body), content_type=content_type
        )

    def _get(self, bucket: str, name: str) -> bytes:
        resp = self.client.get_object(bucket, name)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def _put_json(self, bucket: str, name: str, obj: dict) -> None:
        self._put(bucket, name, json.dumps(obj).encode("utf-8"), "application/json")

    def _get_json(self, bucket: str, name: str) -> dict:
        return json.loads(self._get(bucket, name))

    def _put_text(self, doc_id: str, version: int, text: str) -> None:
        self._put(
            DOCS, f"{doc_id}/v{version}.txt", text.encode("utf-8"), "text/plain"
        )

    def create_document(self, name: str, text: str) -> dict:
        now = _now()
        meta = {
            "id": uuid.uuid4().hex,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        self._put_text(meta["id"], 1, text)
        self._put_json(DOCS, f"{meta['id']}/meta.json", meta)
        return meta

    def list_documents(self) -> list[dict]:
        metas = [
            self._get_json(DOCS, obj.object_name)
            for obj in self.client.list_objects(DOCS, recursive=True)
            if obj.object_name.endswith("/meta.json")
        ]
        return sorted(metas, key=lambda m: m["updated_at"], reverse=True)

    def get_document(self, doc_id: str) -> tuple[dict, str]:
        meta = self._get_json(DOCS, f"{doc_id}/meta.json")
        text = self._get(DOCS, f"{doc_id}/v{meta['version']}.txt").decode("utf-8")
        return meta, text

    def save_version(self, doc_id: str, text: str) -> dict:
        meta = self._get_json(DOCS, f"{doc_id}/meta.json")
        meta["version"] += 1
        meta["updated_at"] = _now()
        self._put_text(doc_id, meta["version"], text)
        self._put_json(DOCS, f"{doc_id}/meta.json", meta)
        return meta

    def save_run(self, run: dict) -> None:
        self._put_json(RUNS, f"{run['id']}.json", run)

    def list_runs(self) -> list[dict]:
        return [
            self._get_json(RUNS, obj.object_name)
            for obj in self.client.list_objects(RUNS)
            if obj.object_name.endswith(".json")
        ]
