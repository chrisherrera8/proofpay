# Policy Engine Plan

Step 3 of `plans/plan.md`. Branch: `feature/policy-engine`. Kept deliberately small for the demo.

## What it does

After the vision check, a job sits in `VERIFIED` and nothing decides what happens next. The policy engine makes that decision. It reads the vision result, the job amount and the **mandate** (the owner's rules for spending), and returns one of three outcomes plus the reasons:

| Decision | Job moves to | Meaning |
|---|---|---|
| `auto_release` | `RELEASED` | The work is proven and within the rules. Payment may be captured with no human. |
| `needs_approval` | `PENDING_APPROVAL` | The work looks fine, but a rule says a human must look first. An `approvals` row is created. |
| `reject` | `REJECTED` | The work is not good enough. The cleaner can re-clean and resubmit (`REJECTED → SUBMITTED` already exists). |

The LLM never decides this. The vision model only reports what it sees per item; the engine is plain Python that anyone can read and test.

## The mandate (simplified)

Only three rules, all taken from the existing `mandates` table columns:

| Field | Demo default | Used for |
|---|---|---|
| `min_score` | 0.80 | Below this score the job is rejected. |
| `auto_release_ceiling` | $25.00 | Jobs above this amount always need a human. |
| `required_items` | `[]` (list of checklist labels) | These items must be visible and passing. |

**Cut for the demo** (matches the plan's scope-cuts list): the monthly cap and the approved-subcontractor list. Jobs have no subcontractor field yet, and the cap needs payout history that doesn't exist. The columns stay in the table, unused, so no migration is needed.

There is one mandate for the whole app. `get_mandate(db)` returns the newest row, or the built-in defaults above if the table is empty, so nothing has to be seeded for the engine to work. Seed data (step 5) can insert a row later.

## Rules, in order (first match wins)

The engine looks at the items the vision step reported for the **latest** verification.

1. **Reject** if no checklist item was visible. Reason: nothing could be verified.
2. **Reject** if a **required** item is visible and failed.
3. **Reject** if `score < min_score`.
4. **Needs approval** if a required item was **not visible**. The model can't prove it, so a human decides rather than failing the cleaner outright.
5. **Needs approval** if any other visible item failed (the score still cleared the minimum).
6. **Needs approval** if `amount > auto_release_ceiling`.
7. Otherwise **auto release**.

Every decision returns *all* reasons that apply, not just the first, so the admin screen can show why. Example: a $30 Deluxe job where everything passes returns `needs_approval` with the reason "Amount $30.00 is above the auto-release ceiling of $25.00".

Note that the current scoring makes `score` the share of visible items that passed, so any failure lowers it. With the default 0.80, one failure in four or fewer visible items already drops below the minimum, and rule 5 only triggers with five or more visible items. That is acceptable for the demo; the mandate numbers are the knob to tune.

## How it's built

### 1. `app/policy.py` — the pure engine (no database)

```python
@dataclass(frozen=True)
class MandateRules:  # plain values, no ORM objects
    min_score: Decimal
    auto_release_ceiling: Decimal
    required_items: tuple[str, ...]

@dataclass(frozen=True)
class Decision:
    outcome: Literal["auto_release", "needs_approval", "reject"]
    reasons: list[str]

def evaluate(amount: Decimal, score: Decimal, items: list[dict], rules: MandateRules) -> Decision: ...
```

- `items` is the stored `verification.results["items"]` (`item`, `visible`, `pass`, ...). Labels match case-insensitively, the same way vision scoring does.
- Pure function: same input, same output, nothing to mock. This is what the tests hit hardest.
- `DEFAULT_RULES` lives here, and `get_mandate(db)` (reads the `mandates` table, falls back to defaults) sits next to it.

### 2. `decide(db, job)` — apply a decision to a job

In `app/policy.py` (or a small `app/decisions.py` if it grows):

1. Read the job's latest verification and the mandate.
2. Call `evaluate`.
3. Move the job with the existing `transition()` (`VERIFIED → RELEASED | PENDING_APPROVAL | REJECTED`), actor `policy-engine`, event `POLICY_DECIDED`, payload `{outcome, reasons, rules}`. The audit log records exactly which rules were in force.
4. For `needs_approval`, add an `Approval(status="PENDING", reason=...)` row in the same transaction.

### 3. Hook it into the existing flow

`POST /submit` and `POST /verify` currently end at `VERIFIED`. After a successful vision result they call `decide()` in the same request, so the cleaner's response already shows the final status and the decision. `JobOut` gains a `decision` field (outcome and reasons, read from the latest `POLICY_DECIDED` audit row) so the cleaner page and later the admin page can show it.

If the vision call fails, nothing changes: the job stays `SUBMITTED` and the retry button works as today. If `decide()` itself raises, the job stays `VERIFIED` and a retry endpoint isn't needed for the demo (`POST /verify` is a no-op there; see open question 2).

### 4. Resolving an approval (minimal)

Without this, `PENDING_APPROVAL` is a dead end. One endpoint, no UI yet (the admin UI is step 5):

`POST /api/jobs/{id}/approval` with `{"decision": "approve" | "deny", "decided_by": str, "reason": str | None}`

- `approve`: `PENDING_APPROVAL → RELEASED`, approval row `APPROVED`.
- `deny`: `PENDING_APPROVAL → REJECTED`, approval row `DENIED` (the cleaner can re-clean).
- 409 if the job isn't pending. Both write an audit row through `transition()`.
- No auth in the demo (same as the rest of the app); `decided_by` is free text. The admin UI step adds a login or at least an obvious "admin" gate.

## Tests

- `tests/test_policy.py` (pure, no DB, fast): one test per rule, plus rule order and combined reasons.
  - all pass at $10 → auto release
  - nothing visible → reject
  - required item failed → reject; required item not visible → needs approval
  - score exactly at `min_score` → passes the gate; just under → reject
  - amount exactly at the ceiling → auto release; one cent over → needs approval
  - case-insensitive label match for required items
  - several reasons returned together
- `tests/test_cleaner_api.py` additions (with `FakeVision`): submit ends in `RELEASED`, `PENDING_APPROVAL` and `REJECTED` for the three cases; the audit log has `POLICY_DECIDED` and the chain verifies; the approval row exists; a re-clean after rejection reaches a new decision.
- Approval endpoint tests: approve, deny, not-pending (409), unknown job (404), double decision (409).
- Existing tests that assert `VERIFIED` after submit will now see `RELEASED` (or the other outcomes) and need updating. This is the main cost of auto-running the engine.

## Order of work

1. `app/policy.py`: dataclasses, `evaluate`, defaults, `get_mandate`. Pure tests first.
2. `decide()` and the audit/approval writes, with DB tests.
3. Hook into `/submit` and `/verify`, add `decision` to `JobOut`, fix the old `VERIFIED` assertions.
4. Approval endpoint and tests.
5. Small web change: show the decision and its reasons on `/cleaner/:jobId` (e.g. "Released", "Waiting for approval: amount above ceiling", "Rejected: Kitchen failed").

Each step is one commit, reviewed before the next.

## Open questions

1. **Run automatically or on demand?** The plan above runs it inside `/submit`, which keeps the demo flow to one click. The alternative is a separate `POST /api/jobs/{id}/decide` that an admin or the cleaner page triggers; it leaves the existing tests alone but adds a step. Recommended: automatic.
2. **Rule 4 (required item not visible → human):** reject it instead if you want a stricter demo. Recommended: keep as needs approval, so all three outcomes are easy to show.
3. **Default numbers** (0.80 and $25): chosen so Basic ($10) and Deep ($20) can auto-release while Deluxe ($30) needs approval. Change them if you want a different demo story.

## Out of scope here

Capture, Payouts and webhooks (step 4, which consumes `RELEASED`), the admin UI (step 5), monthly caps and subcontractor lists, and the rejection agent that drafts the re-clean message.
