import uuid
import httpx
import structlog
from .models import ProcurementRecord, Tombstone
from .renderer import render

log = structlog.get_logger(service="placsp")

def object_uuid(syndication_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://placsp.id/{syndication_id}"))

class Upserter:
    def __init__(self, base_url, api_key, class_name, timeout=300, transport=None, batch_size=100):
        self.base = base_url.rstrip("/")
        self.cls = class_name
        self.batch_size = batch_size
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._c = httpx.Client(timeout=timeout, transport=transport, headers=headers)

    def get_stored(self, sid: str):
        r = self._c.get(f"{self.base}/v1/objects/{self.cls}/{object_uuid(sid)}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("properties", {})

    def upsert(self, records: list[ProcurementRecord], vectors: list[list[float]]) -> int:
        objects = []
        for rec, vec in zip(records, vectors):
            _, props = render(rec)
            objects.append({"class": self.cls, "id": object_uuid(rec.syndication_id),
                            "vector": vec, "properties": props})
        succeeded = 0
        # Weaviate rejects oversized request bodies (400 / dropped connection), so
        # send objects in bounded chunks rather than one giant POST.
        for i in range(0, len(objects), self.batch_size):
            succeeded += self._post_batch(objects[i:i + self.batch_size])
        return succeeded

    def _post_batch(self, objects: list[dict]) -> int:
        if not objects:
            return 0
        r = self._c.post(f"{self.base}/v1/batch/objects", json={"objects": objects})
        r.raise_for_status()
        results = r.json()
        failed = [o for o in results if (o.get("result") or {}).get("status") != "SUCCESS"]
        if failed:
            for o in failed[:3]:
                errs = ((o.get("result") or {}).get("errors") or {}).get("error") or []
                log.warning("batch_object_failed", id=o.get("id"),
                            error=errs[0].get("message") if errs else "unknown")
            if len(failed) > 3:
                log.warning("batch_object_failed", additional=len(failed) - 3)
        return len(objects) - len(failed)

    def delete(self, sid: str) -> None:
        r = self._c.delete(f"{self.base}/v1/objects/{self.cls}/{object_uuid(sid)}")
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def apply_tombstones(self, tombs: list[Tombstone]) -> int:
        for t in tombs:
            self.delete(t.syndication_id)
        return len(tombs)
