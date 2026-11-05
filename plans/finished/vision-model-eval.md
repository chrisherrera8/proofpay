# ProofPay: Vision Model Eval (spike 4)

Notes from the first vision test run on Nov 2, 2026. Companion to `plan.md` section 4 and `step1-spikes.md` (spike 4). The spike is **not finished**: no model has been chosen, and the test itself needs fixes first (see "Problems with the test").

Harness: `spikes/vision_spike.py`. Photos and labels live in `spikes/vision_photos/` (gitignored).

## Setup

- 9 cases, one before and one after image each: `bathroom1`, `bathroom2`, `bedroom1`, `bedroom2`, `bedroom3`, `kitchen1`, `kitchen2`, `kitchen3`, `kitchen4`.
- All images are small (282 to 610px on the longest side), so the 1024px resize does nothing.
- `bathroom2`'s before photo is identical to `bathroom1`'s, and `kitchen4`'s before is identical to `kitchen2`'s.
- The after photos for `bathroom2` and `kitchen4` look AI-generated. They were resized to match their before photo's dimensions and saved as PNG. `kitchen4` still carries a watermark in the pixels.
- Files have random names (so names don't leak anything). Originals were backed up to the session scratchpad under `/tmp`, which is temporary.
- Each model gets the before and after image plus a per-room checklist (`checklists.json`), and returns JSON: per-item pass/fail, confidence, a note, an overall pass and a score. An item the model can't see is told to fail.
- Models: `gemini-3.5-flash` and `claude-haiku-5-5`. Labels are in `labels.json`.

## Results

Your labels against each model's overall verdict (✓ = matches your label).

| Case | Your label | Gemini 3.5 Flash | Claude Haiku 5.5 |
|---|---|---|---|
| bathroom1 | pass | pass ✓ | pass ✓ |
| bathroom2 | pass | fail | fail |
| bedroom1 | pass | pass ✓ | fail |
| bedroom2 | pass | pass ✓ | fail |
| bedroom3 | pass | pass ✓ | fail |
| kitchen1 | pass | fail | fail |
| kitchen2 | pass | fail | fail |
| kitchen3 | fail | fail ✓ | fail ✓ |
| kitchen4 | fail | fail ✓ | fail ✓ |
| **Correct** | | **6 / 9** | **3 / 9** |

| | Gemini 3.5 Flash | Claude Haiku 5.5 |
|---|---|---|
| Latency per call | about 6-35s (includes rate-limit waits; single calls roughly 6-20s) | about 2.6-7s |
| Avg input tokens per job | about 2,340 | about 680 |
| Avg output tokens per job | about 260 | about 850 |
| Cost per job | not calculated; prices not yet confirmed | not calculated; prices not yet confirmed |

Both models passed the two "fail" cases (`kitchen3`, `kitchen4`) and missed the same three "pass" cases (`bathroom2`, `kitchen1`, `kitchen2`). Neither passed a case labelled "fail". With 9 cases, one case is about 11 points, so this is a rough signal only.

## Why the models failed the three cases

I ran Gemini with `-v` (item notes) on `bathroom2`, `kitchen1` and `kitchen2`, then looked at the `bathroom2` and `kitchen2` photos myself.

- **bathroom2: the model is right.** The after photo is only partly cleaned. A pile of clothes is still on the floor, there's debris around the toilet, cups and bottles cover the counter, and items are still in the tub. It's far better than the before, which is buried in trash, but a customer wouldn't accept it. Gemini scored it 0.0 with confidence 0.9 or higher on every item. The label should probably be "fail", or the test needs a "partial" outcome.
- **kitchen2: wrong checklist.** The photos show the inside of an oven, from burnt-on grime to clean, so "pass" is correct. The kitchen checklist asks about floors, counters, sink and trash, none of which are in frame, so every item failed with "not visible". Claude also scored it 0.
- **kitchen1: partly the rule I added.** Gemini passed the counters and the stovetop, but failed floors, sink and trash because they were "cropped out" or "not visible". That is the prompt's "can't see it, fail it" rule being too harsh when the cleaner photographed only part of the room.
- **Claude and the bedrooms.** Claude failed all three bedrooms on "surfaces are dusted and clear" and "trash has been removed". These are hard to judge from a still photo. Gemini passed all three.

## Problems with the test (not the models)

1. `bathroom2` is probably mislabelled, or needs a "partial" outcome.
2. `kitchen2` needs its own checklist (oven interior). The room-prefix scheme only knows kitchen, bathroom and bedroom.
3. "Not visible means fail" is too strict. Marking such items "not applicable" and scoring only the visible ones is fairer.
4. The generated after photos (`bathroom2`, `kitchen4`) and the reused before photos mean those cases test less than real cleaner photos would.
5. The images are small and low resolution.

## Product implications (for plan sections 2 and 4)

- A cleaner who photographs one counter must not pass a whole room. If "not visible" becomes "not applicable", the app needs a **minimum photo set**: at least one required shot per checklist item, or a rule that too few judgeable items fails the job.
- Checklist items that photos can't show well (such as "trash removed") need a required shot, or should come off the checklist.
- The policy engine (deterministic Python) should treat a verification with too few judgeable items as `needs_approval`, not `auto_release`.
- Jobs may need job-type checklists (oven clean vs a general kitchen), not only room-type ones.

## Harness fixes made along the way

- `gemini-2.5-flash` returns 404 ("no longer available to new users"). The default is now `gemini-3.5-flash`. `gemini-3.8-flash` hit a 503 and then the free-tier limit of 5 requests per minute.
- The script retries 429 and 503 errors, waiting as long as Google says.
- Haiku 5.5 rejects the `temperature` parameter, so it was removed.
- Claude's reply has other content blocks before the text, so only the text blocks are read.
- Claude's `max_tokens` is 2500. At 1000, replies were truncated and the JSON broke.
- Flags: `-v` prints every item's note; `--cases=a,b` limits which cases run.

## Still to do

- Decide the `bathroom2` label and a `kitchen2` oven checklist, then loosen the "not visible" rule.
- Rerun both models. Add more real photos if possible, ideally full-room shots from a phone.
- Look up current per-token prices for both models and work out the real cost per job. Plan section 4's prices are unconfirmed.
- Pick the model. Gemini leads on this run (6/9 against 3/9), but that run is dominated by test problems.
- Update plan section 4 with the outcome. The script changes aren't committed yet.
