import uuid
import httpx
import structlog
from placsp.core.models import ProcurementRecord
from placsp.parsers.renderer import render

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

    def upsert(self, records: list[ProcurementRecord], vectors: list[list[float]]) -> int:
        return self.upsert_rendered([r.syndication_id for r in records], [render(r)[1] for r in records], vectors)

    def upsert_rendered(self, sids: list[str], props: list[dict], vectors: list[list[float]]) -> int:
        """Batch insert records already rendered (render() -> properties), one vector each."""
        objects = [{"class": self.cls, "id": object_uuid(sid), "vector": vec, "properties": p}
                   for sid, p, vec in zip(sids, props, vectors)]
        succeeded = 0
        # Weaviate rejects oversized request bodies (400 / dropped connection), so
        # send objects in bounded chunks rather than one giant POST.
        for i in range(0, len(objects), self.batch_size):
            succeeded += self._post_batch(objects[i:i + self.batch_size])
        return succeeded

    def post_batch_raw(self, objects: list[dict]) -> int:
        """Batch insert pre-formatted Weaviate object dictionaries."""
        succeeded = 0
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
