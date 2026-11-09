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


# --- provider edge cases ---------------------------------------------------------------------

OK_REPLY = httpx.Response(200, json=gemini_reply([item(c) for c in CHECK]))


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr("app.vision.gemini.time.sleep", calls.append)
    return calls


@respx.mock
def test_gemini_gives_up_after_three_503s(sleeps):
    route = respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(503, text="busy"))
    with pytest.raises(VisionError, match="503"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    assert route.call_count == 3
    assert sleeps == [3, 6]  # backoff between tries, no sleep after the last one


@respx.mock
def test_gemini_tries_setting_is_respected(sleeps):
    route = respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(503, text="busy"))
    with pytest.raises(VisionError):
        GeminiProvider("k", "m", tries=1).verify([IMG], [IMG], CHECK)
    assert route.call_count == 1 and sleeps == []


@respx.mock
def test_gemini_429_waits_for_the_retry_delay_it_is_told(sleeps):
    respx.post(url__regex=r".*generateContent").mock(side_effect=[
        httpx.Response(429, text="Quota exceeded. Please retry in 2.5s."), OK_REPLY])
    assert GeminiProvider("k", "m").verify([IMG], [IMG], CHECK).overall_pass
    assert sleeps == [3.5]  # the told delay plus a second


@respx.mock
def test_gemini_retry_delay_is_capped_at_20_seconds(sleeps):
    respx.post(url__regex=r".*generateContent").mock(side_effect=[
        httpx.Response(429, text="retry in 57.3s"), OK_REPLY])
    GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    assert sleeps == [20]


@respx.mock
def test_gemini_429_without_a_delay_uses_linear_backoff(sleeps):
    respx.post(url__regex=r".*generateContent").mock(side_effect=[
        httpx.Response(429, text="slow down"), httpx.Response(429, text="slow down"), OK_REPLY])
    GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    assert sleeps == [3, 6]


@respx.mock
def test_gemini_does_not_retry_other_errors(sleeps):
    route = respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(500, text="oops"))
    with pytest.raises(VisionError, match="500"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    assert route.call_count == 1 and sleeps == []


@respx.mock
def test_gemini_timeout_is_a_vision_error_and_not_retried(sleeps):
    route = respx.post(url__regex=r".*generateContent").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(VisionError, match="reach"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    assert route.call_count == 1


@respx.mock
def test_gemini_bad_json_from_the_model_is_a_vision_error():
    reply = {"candidates": [{"content": {"parts": [{"text": "Sure! The kitchen looks clean."}]}}]}
    respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(200, json=reply))
    with pytest.raises(VisionError, match="valid JSON"):
        GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)


@respx.mock
def test_gemini_json_wrapped_in_a_code_fence_is_accepted():
    text = "```json\n" + json.dumps({"items": [item(c) for c in CHECK]}) + "\n```"
    reply = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    respx.post(url__regex=r".*generateContent").mock(return_value=httpx.Response(200, json=reply))
    r = GeminiProvider("k", "m").verify([IMG], [IMG], CHECK)
    assert r.overall_pass and (r.input_tokens, r.output_tokens) == (0, 0)  # no usageMetadata


def test_non_numeric_confidence_becomes_zero():
    for bad in ("high", None, [], {}):
        r = score_answer({"items": [item("Kitchen", conf=bad)]}, ["Kitchen"], "m")
        assert r.items[0].confidence == 0.0, bad
    assert score_answer({"items": [item("Kitchen", conf="0.8")]}, ["Kitchen"], "m").items[0].confidence == 0.8
    assert score_answer({"items": [item("Kitchen", conf=-3)]}, ["Kitchen"], "m").items[0].confidence == 0.0


def test_note_is_truncated_to_500_characters():
    long = dict(item("Kitchen"), note="x" * 900)
    assert len(score_answer({"items": [long]}, ["Kitchen"], "m").items[0].note) == 500
    exact = dict(item("Kitchen"), note="y" * 500)
    assert len(score_answer({"items": [exact]}, ["Kitchen"], "m").items[0].note) == 500


def test_duplicate_labels_in_the_checklist_each_get_an_entry():
    r = score_answer({"items": [item("Kitchen")]}, ["Kitchen", "Kitchen"], "m")
    assert [i.item for i in r.items] == ["Kitchen", "Kitchen"]
    assert r.score == 1.0 and r.overall_pass is True


def test_duplicate_labels_in_the_answer_last_one_wins():
    r = score_answer({"items": [item("Kitchen", passed=True), item("Kitchen", passed=False)]}, ["Kitchen"], "m")
    assert r.items[0].passed is False and r.overall_pass is False


def test_labels_match_ignoring_case_and_surrounding_whitespace():
    r = score_answer({"items": [item("  KITCHEN ")]}, ["kitchen"], "m")
    assert r.items[0].visible is True and r.items[0].item == "kitchen"


def test_non_dict_entries_in_the_answer_are_skipped():
    r = score_answer({"items": ["Kitchen", None, item("Kitchen")]}, ["Kitchen"], "m")
    assert r.items[0].visible is True
