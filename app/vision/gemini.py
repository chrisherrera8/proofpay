"""Gemini provider (REST, no SDK)."""
import base64
import logging
import re
import time

import httpx

from app.vision.base import ImageInput, VisionError, VisionResult, build_prompt, parse_model_json, score_answer

log = logging.getLogger(__name__)

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider:
    def __init__(self, api_key: str, model: str, *, timeout: float = 90, tries: int = 3):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.tries = tries

    def verify(self, before: list[ImageInput], after: list[ImageInput], checklist: list[str]) -> VisionResult:
        prompt = build_prompt(checklist, len(before), len(after))
        parts: list[dict] = [{"text": prompt}] + [
            {"inline_data": {"mime_type": im.mime_type, "data": base64.b64encode(im.data).decode()}}
            for im in [*before, *after]
        ]
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        d = self._post(body)
        try:
            text = d["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionError("Gemini returned no answer (possibly blocked)") from exc
        usage = d.get("usageMetadata", {})
        return score_answer(
            parse_model_json(text), checklist, self.model,
            usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0),
        )

    def _post(self, body: dict) -> dict:
        for attempt in range(self.tries):
            try:
                r = httpx.post(
                    _URL.format(model=self.model), headers={"x-goog-api-key": self.api_key},
                    json=body, timeout=self.timeout,
                )
            except httpx.HTTPError as exc:
                raise VisionError(f"Could not reach Gemini: {type(exc).__name__}") from exc
            if r.is_success:
                return r.json()
            # Free-tier rate limits and "high demand" are transient: wait and retry.
            if r.status_code in (429, 503) and attempt < self.tries - 1:
                m = re.search(r"retry in ([\d.]+)s", r.text)
                time.sleep(min(float(m.group(1)) + 1 if m else 3 * (attempt + 1), 20))
                continue
            log.warning("Gemini %s: %s", r.status_code, r.text[:300])
            raise VisionError(f"Gemini error {r.status_code}")
        raise VisionError("Gemini unavailable")  # pragma: no cover
