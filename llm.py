"""LLM adapter for the local Jev-style evaluator.

Edit the `llm` function to use any model provider you want. The rest of the
application only expects this shape:

    llm(system_prompt: str, user_prompt: str) -> str

The returned string can be any text. `server.py` handles interpretation,
post-processing, and repair retries.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _extract_text(response: dict) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]

    chunks: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks)


def llm(system_prompt: str, user_prompt: str) -> str:
    """Return a string response for a system prompt and user prompt.

    Default implementation: OpenAI Responses API with gpt-5-mini.
    To use another provider, keep this function signature and replace the body.
    """

    _load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in .env or the environment.")

    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        "reasoning": {
            "effort": os.environ.get("OPENAI_REASONING_EFFORT", "minimal"),
        },
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc

    text = _extract_text(body).strip()
    if not text:
        raise RuntimeError("OpenAI returned no text output.")
    return text
