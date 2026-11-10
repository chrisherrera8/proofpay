# Design rules: Sparkle & Shine / ProofPay web

Read this before any UI change. The tokens live in `src/styles.css`; this file says how to use them.

## Brand and feel

Sparkle & Shine is a home-cleaning service. ProofPay is the trust layer: the customer's money is held until before/after photos are verified, then the cleaner is paid. The UI should feel **calm, trustworthy and tidy**: warm off-white paper, one deep evergreen, generous whitespace, quiet borders. Not fintech dark mode, not playful, not SaaS-gradient.

Light mode only. Don't add `dark:` variants.

## Color tokens

Use the semantic Tailwind classes (`bg-primary`, `text-muted-foreground`, `border-border`, ...). Never raw hex in components, never default palette classes (`bg-blue-500`, `text-gray-600`).

| Token | Value | Use | Contrast |
|---|---|---|---|
| `background` | `#FAF8F4` | page | |
| `foreground` | `#1B211E` | body text | 15.4:1 on background |
| `card` | `#FFFFFF` | cards, inputs | |
| `muted` | `#F2EFE8` | quiet panels, section bands | |
| `muted-foreground` | `#5C6560` | secondary text | 5.7:1 on background, 6.0:1 on card |
| `primary` | `#17594A` (evergreen) | the one main action per view, links, focus ring | white on it 8.2:1 |
| `accent` | `#E6F0EB` | selected/hover tint, icon wells | `accent-foreground #17594A` 7.0:1 |
| `honey` | `#F6D58A` | "Most popular" and similar highlights only | `honey-foreground #6B4A00` 5.7:1 |
| `success` / `success-foreground` | `#E5F3EA` / `#156B43` | passed, paid | 5.7:1 |
| `warning` / `warning-foreground` | `#FDF1DC` / `#8A4B00` | waiting, needs attention | 6.1:1 |
| `destructive` (+ `danger` bg `#FDECEA`) | `#B42318` | errors, rejected, remove | 6.6:1 on card |
| `border` | `#E4E1D8` | card and divider lines (decorative) | |
| `input` | `#8C8A82` | form control borders | 3.5:1 on card |

## Type

- One family: **Inter** (variable, self-hosted via `@fontsource-variable/inter`). No other fonts, no Google Fonts call.
- Scale (Tailwind classes): `text-xs` 12 · `text-sm` 14 · `text-base` 16 · `text-lg` 18 · `text-xl` 20 · `text-2xl` 24 · `text-3xl` 30 · `text-5xl` 48 (hero only).
- Weights: 400 body, 500 labels/buttons, 600 headings. No 800/900.
- Headings use `tracking-tight`. Body line length max ~65ch (`max-w-prose`).
- Money uses `tabular-nums`.

## Spacing, radius, elevation

- 4px grid: only Tailwind's default spacing steps. No arbitrary values (`p-[13px]`).
- Page gutter `px-4` (16px) on phones, `sm:px-6`. Content widths: `max-w-5xl` marketing, `max-w-xl` forms and job pages.
- Section rhythm: `py-16 sm:py-24` for marketing sections, `gap-6` between cards in a stack.
- Radius: `--radius` is 12px. Cards `rounded-xl`, controls `rounded-lg`, pills `rounded-full`.
- Shadows: `shadow-xs` on cards at most. Elevation comes from borders, not shadows.

## Components

Use what exists before writing markup. Add registry components with the shadcn MCP (`npx shadcn@4.23.0 add <name>` from `web/`). App-level components go in `src/components/`.

| Need | Use |
|---|---|
| Actions | `Button` (`default` for the primary action, `outline`/`ghost` for the rest, `size="lg"` on mobile-critical actions) |
| Grouped content | `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter` |
| Form fields | `Field` (src/components/field.tsx) = `Label` + `Input` + hint/error wired with `aria-describedby` |
| Messages | `Alert` (`variant="destructive"` for errors) |
| Job state | `StatusBadge` (src/components/status-badge.tsx). Never print raw statuses like `PAID_OUT` |
| Progress through the job | `JobTimeline` (src/components/job-timeline.tsx) |
| Loading | `Skeleton` shaped like the content, never a bare "Loading…" |
| Icons | `lucide-react`, `size-4` inline, `size-5` in icon wells. No emoji as icons |

## Banned patterns

- Purple/indigo anything, gradients on buttons or text, glassmorphism, glow.
- Emoji as icons or decoration (✨ ✅ ❌ 💸 🎉 ...).
- Centering everything: center only the hero and section headings; content is left-aligned.
- Cards inside cards.
- More than one filled button in the page body (the header's "Book a clean" is the one allowed extra).
- Raw hex, arbitrary values, default palette colors, `!important` (only the reduced-motion reset in `styles.css` uses it).
- Bare uppercase enum values shown to users.
- Icons without a text label unless they have `aria-label`.

## Accessibility (required)

- One `h1` per page; headings in order; `header`/`main`/`footer` landmarks (set in `Layout`).
- Every input has a visible `Label`; errors use `aria-invalid` and `aria-describedby`; summary errors use `role="alert"`.
- Visible focus ring on everything interactive (`focus-visible:ring-ring/50 ring-[3px]` from the shadcn components; keep it).
- Touch targets at least 44px on phone pages (cleaner flow): use `size="lg"` buttons and `h-11` inputs.
- Images have meaningful `alt`. Status is never color alone: always text, and an icon where it helps.
- Respect `prefers-reduced-motion` (the base CSS disables transitions).

## Done means

The screenshot check in `web/CLAUDE.md` passed at 390px and 1280px, no new console errors, `npm run build` passes.
