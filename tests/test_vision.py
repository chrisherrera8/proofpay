import json

import httpx
import pytest
import respx

from app.vision.base import ImageInput, VisionError, build_prompt, parse_model_json, score_answer
from app.vision.gemini import GeminiProvider

CHECK = ["Kitchen", "Bathroom", "Floors"]


def item(name, visible=True, passed=True, conf=0.9):
    return {"item": name, "visible": visible, "pass": passed, "confidence": conf, "note": "n"}


def test_score_all_pass():
    r = score_answer({"items": [item(c) for c in CHECK], "overall_pass": False, "score": 0.1}, CHECK, "m")
    assert r.overall_pass is True and r.score == 1.0  # the model's own verdict is ignored


def test_score_visible_failure_fails_job():
    r = score_answer({"items": [item("Kitchen"), item("Bathroom", passed=False), item("Floors")],
                      "overall_pass": True, "score": 1}, CHECK, "m")
    assert r.overall_pass is False and r.score == 0.67


def test_not_visible_items_are_ignored_even_if_model_marks_them_failed():
    r = score_answer({"items": [item("Kitchen"), item("Bathroom", visible=False, passed=False),
                                item("Floors", visible=False)]}, CHECK, "m")
    assert r.overall_pass is True
    assert r.items[1].passed is True and r.items[1].visible is False


def test_nothing_visible_fails():
    r = score_answer({"items": [item(c, visible=False) for c in CHECK]}, CHECK, "m")
    assert r.overall_pass is False and r.score == 0.0


def test_missing_items_follow_checklist_order_and_count_as_not_visible():
    r = score_answer({"items": [item("floors")]}, CHECK, "m")  # case-insensitive match
    assert [i.item for i in r.items] == CHECK
    assert [i.visible for i in r.items] == [False, False, True]


def test_confidence_clamped_and_bad_shapes_rejected():
    assert score_answer({"items": [item("Kitchen", conf=7)]}, ["Kitchen"], "m").items[0].confidence == 1.0
    with pytest.raises(VisionError):
        score_answer({"items": "nope"}, CHECK, "m")
    with pytest.raises(VisionError):
        parse_model_json("not json")
    assert parse_model_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_prompt_layout():
    assert "Image 1 is BEFORE, image 2 is AFTER" in build_prompt(CHECK, 1, 1)
    assert "Images 1-2 are BEFORE photos and images 3-5 are AFTER" in build_prompt(CHECK, 2, 3)


IMG = ImageInput(b"\xff\xd8\xff", "image/jpeg")


def gemini_reply(items):
    text = json.dumps({"items": items})
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 2400, "candidatesTokenCount": 300}}


@respx.mock
def test_gemini_happy_path():
    route = respx.post(url__regex=r".*gemini-test:generateContent").mock(
        return_value=httpx.Response(200, json=gemini_reply([item(c) for c in CHECK])))
    r = GeminiProvider("key", "gemini-test").verify([IMG], [IMG, IMG], CHECK)
    assert r.overall_pass and (r.input_tokens, r.output_tokens) == (2400, 300)
    req = route.calls[0].request
    assert req.headers["x-goog-api-key"] == "key"
    parts = json.loads(req.content)["contents"][0]["parts"]
    assert len(parts) == 1 + 3  # prompt + 1 before + 2 after


@respx.mock
def test_gemini_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.vision.gemini.time.sleep", lambda s: None)
    respx.post(url__regex=r".*generateContent").mock(side_effect=[
        httpx.Response(503, text="busy"), httpx.Response(200, json=gemini_reply([item(c) for c in CHECK]))])
    assert GeminiProvider("k", "m").verify([IMG], [IMG], CHECK).overall_pass


@respx.mock
def test_gemini_errors_become_vision_error(monkeypatch):
    monkeypatch.setattr("app.vision.gemini.time.sleep", lambda s: None)
    respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(400, text="bad"))
    with pytest.raises(VisionError, match="400"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(200, json={"candidates": []}))
    with pytest.raises(VisionError, match="no answer"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    respx.post(url__regex=r".*generateContent").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(VisionError, match="reach"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
