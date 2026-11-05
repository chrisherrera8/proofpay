"""Spike 4: compare vision models on before/after cleaning photos.

Layout (run from the project root), one image per case folder:
  spikes/vision_photos/before/<case>/<any name>.png|jpg|jpeg
  spikes/vision_photos/after/<case>/<any name>.png|jpg|jpeg
  spikes/vision_photos/labels.json   {"kitchen1": "pass", "bathroom1": "fail", ...}
  spikes/vision_photos/checklists.json   {"kitchen": [items...], "bathroom": [...]}
The room is the case-name prefix (kitchen1 -> "kitchen"), so it must match a key.

"pass" = the after photo shows the job genuinely done; "fail" = it doesn't
(still dirty, wrong room, same photo as before, etc). Cases missing from
labels.json still run and print results, but don't count toward accuracy.

.env keys: GEMINI_API_KEY and/or ANTHROPIC_API_KEY (optional OPENAI not wired).
Optional overrides: GEMINI_MODEL, ANTHROPIC_MODEL.

Usage:  python3 spikes/vision_spike.py [gemini|claude ...] [-v] [--cases=a,b]
        -v prints every item's note; --cases limits which cases run.
          (default: all with keys)
"""
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = Path(__file__).resolve().parent / "vision_photos"


def build_prompt(checklist):
    return (
        "You verify home-cleaning work. Image 1 is BEFORE, image 2 is AFTER, same room. "
        "Judge each checklist item from the AFTER photo, using BEFORE for comparison. "
        "The cleaner may have photographed only part of the room. If an item is not visible "
        "in the AFTER photo, mark it visible=false and pass=true (not applicable) and do not "
        "let it count against the result; judge overall_pass and score only on the items you can see. "
        "Still fail the visible items if the photos are the same, unrelated to each other, "
        "or too unclear to judge, and fail overall if none of the items are visible. "
        "Reply with JSON only: "
        '{"items":[{"item":str,"visible":bool,"pass":bool,"confidence":number 0-1,"note":str}],'
        '"overall_pass":bool,"score":number 0-1}\nChecklist:\n'
        + "\n".join(f"- {c}" for c in checklist)
    )


def load_env():
    env = {k: os.environ[k] for k in ("GEMINI_MODEL", "ANTHROPIC_MODEL") if k in os.environ}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return env


def jpeg_b64(path, max_side=1024):
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


def gemini(env, imgs, prompt):
    model = env.get("GEMINI_MODEL", "gemini-3.6-flash")
    parts = [{"text": prompt}] + [
        {"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in imgs
    ]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": env["GEMINI_API_KEY"]},
        json={"contents": [{"parts": parts}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    d = r.json()
    u = d.get("usageMetadata", {})
    text = d["candidates"][0]["content"]["parts"][0]["text"]
    return parse_json(text), u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), model


def claude(env, imgs, prompt):
    model = env.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
               for b in imgs] + [{"type": "text", "text": prompt}]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
        json={"model": model, "max_tokens": 2500,
              "messages": [{"role": "user", "content": content}]},
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    d = r.json()
    u = d.get("usage", {})
    text = "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")
    return parse_json(text), u.get("input_tokens", 0), u.get("output_tokens", 0), model


def call_with_retry(fn, env, imgs, prompt, tries=5):
    """Retry 429/503 (free-tier rate limits, high demand), honouring 'retry in Ns'."""
    for attempt in range(tries):
        try:
            return fn(env, imgs, prompt)
        except RuntimeError as e:
            msg = str(e)
            if attempt == tries - 1 or not msg.startswith(("429", "503")):
                raise
            m = re.search(r"retry in ([\d.]+)s", msg)
            wait = float(m.group(1)) + 2 if m else 10 * (attempt + 1)
            print(f"  ...{msg[:3]}, waiting {wait:.0f}s")
            time.sleep(wait)


PROVIDERS = {"gemini": ("GEMINI_API_KEY", gemini), "claude": ("ANTHROPIC_API_KEY", claude)}


def find(folder):
    imgs = sorted(p for p in folder.iterdir()
                  if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if len(imgs) != 1:
        raise FileNotFoundError(f"expected exactly 1 image in {folder}, found {len(imgs)}")
    return imgs[0]


def main():
    env = load_env()
    labels = json.loads((PHOTOS / "labels.json").read_text())
    checklists = json.loads((PHOTOS / "checklists.json").read_text())
    bad = {c: v for c, v in labels.items() if v not in ("pass", "fail", "")}
    if bad:
        sys.exit(f"labels must be 'pass', 'fail' or '' (unlabeled): {bad}")
    cases = sorted(p.name for p in (PHOTOS / "before").iterdir() if p.is_dir())
    missing = [c for c in cases if not (PHOTOS / "after" / c).is_dir()]
    if missing:
        sys.exit(f"cases with no after folder: {missing}")
    unknown = [c for c in labels if c not in cases]
    if unknown:
        sys.exit(f"labels.json has cases with no folders: {unknown}")
    args = sys.argv[1:]
    verbose = "-v" in args
    only = next((a.split("=", 1)[1].split(",") for a in args if a.startswith("--cases=")), None)
    if only:
        cases = [c for c in cases if c in only]
    args = [a for a in args if a in PROVIDERS]
    names = args or [n for n, (k, _) in PROVIDERS.items() if env.get(k)]
    if not names:
        sys.exit("No API keys in .env (GEMINI_API_KEY / ANTHROPIC_API_KEY)")
    summary = {}
    for name in names:
        key, fn = PROVIDERS[name]
        if not env.get(key):
            print(f"skip {name}: {key} missing")
            continue
        right = 0
        tin = tout = 0
        lat = []
        model = "?"
        print(f"\n=== {name} ===")
        scored = 0
        for case in cases:
            want = labels.get(case) or None
            room = next((r for r in checklists if case.startswith(r)), None)
            if room is None:
                print(f"{case:20} SKIP no checklist for room (case name must start with one of {list(checklists)})")
                continue
            prompt = build_prompt(checklists[room])
            try:
                imgs = [jpeg_b64(find(PHOTOS / "before" / case)),
                        jpeg_b64(find(PHOTOS / "after" / case))]
            except FileNotFoundError as e:
                print(f"{case:20} SKIP {e}")
                continue
            t = time.time()
            try:
                res, i, o, model = call_with_retry(fn, env, imgs, prompt)
            except Exception as e:  # keep going; report the failure
                print(f"{case:20} ERROR {str(e)[:200]}")
                continue
            lat.append(time.time() - t)
            tin += i
            tout += o
            got = "pass" if res.get("overall_pass") else "fail"
            ok = got == want
            if want:
                scored += 1
                right += ok
            if verbose:
                for x in res.get("items", []):
                    print(f"    [{'pass' if x.get('pass') else 'FAIL'}] {x.get('item')} "
                          f"(conf {x.get('confidence')}): {x.get('note')}")
            fails = [x["item"][:30] for x in res.get("items", []) if not x.get("pass")]
            print(f"{case:20} want={want or '?':4} got={got:4} score={res.get('score')} "
                  f"{('OK ' if ok else 'MISS') if want else '-   '} {lat[-1]:.1f}s in={i} out={o} fails={fails}")
        n = len(lat)
        summary[name] = (model, right, scored, tin, tout, sum(lat) / n if n else 0, n)
    print("\n=== summary ===")
    for name, (model, right, total, tin, tout, avg, n) in summary.items():
        print(f"{name} ({model}): {right}/{total} correct (labeled cases only), avg {avg:.1f}s, "
              f"avg tokens/job in={tin // max(n, 1)} out={tout // max(n, 1)}")
    print("Multiply avg tokens by the provider's current price per 1M tokens to get cost/job.")


if __name__ == "__main__":
    main()
