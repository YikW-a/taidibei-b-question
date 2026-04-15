from __future__ import annotations

import http.client
import json
import re
import time
from urllib import error, request


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        req = request.Request(
            url=f"{self.base_url}/chat/completions",
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
            except (http.client.RemoteDisconnected, error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                if attempt >= 2:
                    raise
                time.sleep(1.0 * (attempt + 1))
        else:  # pragma: no cover
            raise last_error or RuntimeError("LLM request failed.")
        return data["choices"][0]["message"]["content"]


def extract_json_object(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("No JSON object found in response.")
    return json.loads(match.group(0))


__all__ = ["OpenAICompatibleClient", "extract_json_object"]
