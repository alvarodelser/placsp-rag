from concurrent.futures import ThreadPoolExecutor
import httpx

class Embedder:
    def __init__(self, base_url: str, batch_size: int = 48, timeout: float = 600, transport=None, workers: int = 1):
        self.url = base_url.rstrip("/") + "/embed"
        self.batch_size = batch_size
        self.workers = max(1, workers)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _one(self, batch: list[str]) -> list[list[float]]:
        r = self._client.post(self.url, json={"texts": batch, "normalize": True})
        r.raise_for_status()
        return r.json()["embeddings"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        batches = [texts[i:i + self.batch_size] for i in range(0, len(texts), self.batch_size)]
        if self.workers == 1 or len(batches) < 2:
            parts = [self._one(b) for b in batches]
        else:   # several requests in flight keep the vectorizer busy; map keeps the order
            with ThreadPoolExecutor(self.workers) as pool:
                parts = list(pool.map(self._one, batches))
        return [v for p in parts for v in p]
