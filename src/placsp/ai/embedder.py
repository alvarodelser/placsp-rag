import httpx

class Embedder:
    def __init__(self, base_url: str, batch_size: int = 48, timeout: float = 600, transport=None):
        self.url = base_url.rstrip("/") + "/embed"
        self.batch_size = batch_size
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            r = self._client.post(self.url, json={"texts": batch, "normalize": True})
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        return out
