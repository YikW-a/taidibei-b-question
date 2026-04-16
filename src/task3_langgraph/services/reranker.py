from __future__ import annotations

import http.client
import json
import time
from urllib import error, request


class OpenAICompatibleRerankerClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def rerank(self, query: str, documents: list[str], *, top_n: int) -> list[dict]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }
        req = request.Request(
            url=f"{self.base_url}/rerank",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except error.HTTPError as exc:
                last_error = exc
                if exc.code == 429 and attempt < 2:
                    time.sleep(4.0 * (attempt + 1))
                    continue
                raise
            except (http.client.RemoteDisconnected, error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt >= 2:
                    raise
                time.sleep(1.0 * (attempt + 1))
        else:  # pragma: no cover
            raise last_error or RuntimeError("Rerank request failed.")
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        return [item for item in results if isinstance(item, dict)]


__all__ = ["OpenAICompatibleRerankerClient"]
