# UI Revamp Plan (experimental)

**Status (Nov 9): steps 1-5 done on `experiment/ui-revamp`; step 6 (decide) is yours.** Decisions: Inter, light only, brand color changed from teal `#0b7a75` to evergreen `#17594A` on warm off-white `#FAF8F4`, with honey `#F6D58A` as the only highlight color. Notes from the build:
- `shadcn init` hangs on an interactive prompt in this setup, so `components.json` and `src/lib/utils.ts` were written by hand. `shadcn add` also wired `cn` to an unrelated npm package called `cn`; fixed to `@/lib/utils`. Watch for that on future `add` runs.
- The npm cache at `~/.npm` has root-owned files (`npm error EACCES`); run `sudo chown -R 501:20 ~/.npm` once.
- The `.mcp.json` servers need a one-time approval the next time `claude` starts in the repo.
- Screens were checked with Playwright against a mocked API at 390px and 1280px; the PayPal buttons render but load slowly, so screenshots must wait for the iframe. Not yet checked against the real API or a real sandbox payment.

Goal: make the web app (`web/`) look like a designer worked on it, by giving the agent real components, a design rules file it loads every session, and a way to see what it rendered. Branch: `experiment/ui-revamp`. Experimental: nothing here merges to `main` unless the result is clearly better than what's live.

**Timing:** the hackathon deadline is Nov 12, 12:00pm PST, and feature freeze was Nov 9. This work touches only how pages look, not the API or money flow. If it isn't clearly better by Nov 11 evening, the demo runs on the current `main` and this branch waits.

## Where the UI is today

- Vite 5 + React 18 + TypeScript, React Router. Five pages (`Home`, `Book`, `Booked`, `CleanerJobs`, `CleanerJob`), about 520 lines in total.
- One hand-written `web/src/styles.css` (45 lines): six CSS variables (`--brand #0b7a75`, `--ink`, `--muted`, `--bg`, `--card`, `--line`), `system-ui` font, global classes (`.btn`, `.card`, `.form`, `.pick`, `.badge`, ...).
- No Tailwind, no component library, no `@/` path alias, no `CLAUDE.md`, no project MCP servers.

## The three pieces (from the rubric), adapted to this repo

The rubric was written for VS Code + Copilot. We use Claude Code, so MCP servers go in a project `.mcp.json` (checked in) instead of `.vscode/mcp.json`, and rules go in `CLAUDE.md`.

| Rubric item | What we do | Why it's this way |
|---|---|---|
| 1. Real components | shadcn/ui on Tailwind v4, plus the shadcn MCP server | The agent installs and composes existing components instead of writing new React each time. |
| 2. Design context | `web/design.md` (tokens, type scale, spacing, banned patterns, accessibility rules), loaded through `web/CLAUDE.md`. **No Figma MCP**: there are no Figma designs. | A rules file pulls output away from the "average Tailwind" look. Figma can be added later if mockups appear; in Claude Code it doesn't need Copilot. |
| 3. Seeing its own output | Playwright MCP, plus a rule: after any UI change, screenshot the route at 390px and 1280px and read the console | Without it the agent can't tell whether a change looks right. |

## Order of work

Each step is one commit. Build one component or screen at a time, never a whole page in one go.

### 1. Tooling (no visible change)

1. Branch `experiment/ui-revamp` from `main`.
2. Tailwind v4: `npm i -D tailwindcss @tailwindcss/vite`, add the plugin in `vite.config.ts`, `@import "tailwindcss";` at the top of `styles.css`. Keep the existing classes working so the pages look the same at the end of this step.
3. Path alias `@/* → src/*` in `tsconfig.json` and `vite.config.ts` (shadcn needs it).
4. `npx shadcn@<pinned> init` (style `new-york`, base color neutral; we override the colors in step 2). Commits `components.json`, `src/lib/utils.ts`, the CSS variables block.
5. MCP servers in `.mcp.json` at the repo root, versions pinned:
   - shadcn: `npx shadcn@<pinned> mcp init --client claude`
   - Playwright: `claude mcp add --scope project playwright -- npx @playwright/mcp@<pinned>`
6. Check: `npm run build` passes, the five pages look unchanged, `/mcp` in Claude Code lists both servers.

### 2. Design rules file (`web/design.md`)

Written by hand (with the agent), before any component work. Sections:

- **Brand and feel.** Sparkle & Shine is a home-cleaning service; ProofPay is the trust layer (proof photos, payment held until verified). Feel: calm, trustworthy, clean. Not "fintech dark mode", not playful.
- **Color tokens** as shadcn CSS variables (`--primary`, `--background`, `--muted`, `--border`, `--destructive`, plus `--success` and `--warning` for job states). Keep teal `#0b7a75` as `--primary`. Every text/background pair listed with its contrast ratio; body text at least 4.5:1, large text and UI borders at least 3:1.
- **Type scale.** One font family (pick one: e.g. Inter or Geist via `@fontsource`, self-hosted, no Google Fonts call). Fixed steps (12/14/16/20/24/32/40), two weights for body, one for headings.
- **Spacing and radius.** 4px grid; allowed spacing steps; one radius scale (`--radius`).
- **Components.** Which shadcn components we use for what (Button, Card, Badge, Input, Label, Form, Alert, Progress, Skeleton, Sonner toasts, Dialog). Rule: use an existing component before writing markup; new ones go in `src/components/`.
- **Job status display.** One `StatusBadge` mapping every state (`BOOKED` ... `PAID_OUT`, `PENDING_APPROVAL`, `REJECTED`) to a label, color and icon, so states never look different on different pages.
- **Banned patterns.** Purple/indigo gradients, gradient text, emoji as icons (including the ✨ in the logo; use `lucide-react`), centered everything, cards inside cards, more than one primary button per view, arbitrary Tailwind values (`p-[13px]`), raw hex colors in components, default Tailwind palette classes (`bg-blue-500`) instead of tokens.
- **Accessibility (required).** Semantic landmarks and one `h1` per page; every input has a `<Label>`; errors linked with `aria-describedby`; visible focus ring on everything interactive; touch targets at least 44px (cleaners use phones); images have `alt`; status is never shown by color alone; respects `prefers-reduced-motion`.
- **Done means.** The screenshot check in step 3 passed and no console errors.

### 3. Agent rules (`web/CLAUDE.md`)

Short, pointing at `design.md` instead of repeating it:

- Read `web/design.md` before any UI work and follow it.
- Use the shadcn MCP to find and add components; don't hand-write what the registry has.
- After any UI change: run the dev server, use Playwright MCP to screenshot each affected route at 390×844 and 1280×800, read the console, fix what's wrong, and repeat. Report the screenshots you looked at.
- One component or screen per change.

### 4. Foundation components

Theme tokens from `design.md` in `styles.css`, font, then `Layout` (header, footer) and `StatusBadge`. Screenshot check on `/`.

### 5. Screens, one at a time, in demo order

1. `Home` (hero, tier cards)
2. `Book` (tier picker, form, PayPal button area). Don't restyle inside the PayPal button iframe; only its surroundings.
3. `Booked`
4. `CleanerJobs` (mobile first)
5. `CleanerJob` (photo slots, upload, verdicts, payment progress, retry button; mobile first)

After each: screenshot check, then delete the old classes from `styles.css` that the screen no longer uses. At the end `styles.css` should hold only Tailwind imports and tokens.

### 6. Decide

Side-by-side screenshots of `main` and the branch for all five routes at both widths. Merge only if it's clearly better and the full booking → upload → payout flow still works in the sandbox (the same run as the capture-payouts sandbox run).

## Caveats

- Much of the advice behind the rubric comes from tool vendors; the pattern (components + rules file + visual check) is consistent across independent writers, the specific product claims aren't.
- This gets a competent first draft, not a finished design. Expect to hand-adjust spacing and hierarchy after each screen.
- Generated UI tends to fail contrast and skip labels and focus states. That's why the accessibility rules are in `design.md` and the screenshot check includes a keyboard tab-through on forms.

## Open questions

- Font: Inter or Geist (or keep `system-ui`)?
- Keep teal `#0b7a75` as the brand color, or revisit it in `design.md`?
- Add a dark mode, or light only for the demo? (Proposed: light only.)
