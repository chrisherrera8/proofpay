"""Vision verification: provider interface, prompt, and deterministic scoring of the model's answer.

The model only reports what it sees per checklist item. Whether the job passed is decided here, in
plain code, so the LLM never decides an outcome by itself.
"""
import json
from dataclasses import dataclass, field
from typing import Protocol


class VisionError(Exception):
    """The provider failed (network, rate limit, unusable answer). The job stays SUBMITTED."""


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    mime_type: str


@dataclass
class ItemResult:
    item: str
    visible: bool
    passed: bool
    confidence: float
    note: str

    def as_dict(self) -> dict:
        return {
            "item": self.item, "visible": self.visible, "pass": self.passed,
            "confidence": self.confidence, "note": self.note,
        }


@dataclass
class VisionResult:
    items: list[ItemResult]
    overall_pass: bool
    score: float
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict = field(default_factory=dict)


class VisionProvider(Protocol):
    model: str

    def verify(self, before: list[ImageInput], after: list[ImageInput], checklist: list[str]) -> VisionResult: ...


def build_prompt(checklist: list[str], n_before: int, n_after: int) -> str:
    if n_before == 1 and n_after == 1:
        layout = "Image 1 is BEFORE, image 2 is AFTER, same room. "
    else:
        layout = (
            f"Images 1-{n_before} are BEFORE photos and images {n_before + 1}-{n_before + n_after} "
            "are AFTER photos, taken around the same home. "
        )
    return (
        "You verify home-cleaning work. " + layout +
        "Judge each checklist item from the AFTER photos, using BEFORE for comparison. "
        "The cleaner may have photographed only part of the home. If an item is not visible "
        "in the AFTER photos, mark it visible=false and pass=true (not applicable) and do not "
        "let it count against the result; judge overall_pass and score only on the items you can see. "
        "Still fail the visible items if the photos are the same, unrelated to each other, "
        "or too unclear to judge, and fail overall if none of the items are visible. "
        "Reply with JSON only: "
        '{"items":[{"item":str,"visible":bool,"pass":bool,"confidence":number 0-1,"note":str}],'
        '"overall_pass":bool,"score":number 0-1}\nChecklist:\n'
        + "\n".join(f"- {c}" for c in checklist)
    )


def parse_model_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisionError("Model did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise VisionError("Model JSON was not an object")
    return data


def _clamp01(v, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def score_answer(data: dict, checklist: list[str], model: str, in_tok: int = 0, out_tok: int = 0) -> VisionResult:
    """Turn the model's JSON into a VisionResult with one entry per checklist item, in checklist order.

    An item the model skipped counts as not visible. overall_pass is computed here: at least one item
    visible and every visible item passing. The model's own overall_pass and score are ignored for the
    decision; the score is the share of visible items that passed, so it can't be talked up.
    """
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise VisionError("Model answer has no items list")
    by_label = {str(x.get("item", "")).strip().lower(): x for x in raw_items if isinstance(x, dict)}

    items: list[ItemResult] = []
    for label in checklist:
        x = by_label.get(label.strip().lower())
        if x is None:
            items.append(ItemResult(label, False, True, 0.0, "Not assessed by the model"))
            continue
        visible = bool(x.get("visible", True))
        # Not-visible items are not applicable: they never fail the job.
        passed = True if not visible else bool(x.get("pass", False))
        items.append(ItemResult(label, visible, passed, _clamp01(x.get("confidence")), str(x.get("note", ""))[:500]))

    visible_items = [i for i in items if i.visible]
    overall = bool(visible_items) and all(i.passed for i in visible_items)
    score = round(sum(i.passed for i in visible_items) / len(visible_items), 2) if visible_items else 0.0
    return VisionResult(items, overall, score, model, in_tok, out_tok, raw=data)
