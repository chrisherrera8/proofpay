# Web app (Vite + React + TypeScript + Tailwind v4 + shadcn/ui)

## UI work rules

1. Read `design.md` (this folder) before any UI change and follow it. It holds the tokens, type scale, spacing, component choices, banned patterns and accessibility rules.
2. Use the shadcn MCP server to find and add components (`.mcp.json` at the repo root). Don't hand-write something the registry has. Generated components go in `src/components/ui/` and import `cn` from `@/lib/utils`.
3. One component or one screen per change, not whole flows.
4. After any UI change, check it visually with the Playwright MCP server:
   - run `npm run dev` (port 5173); without the API running, use `page.route` to mock `http://localhost:8000/api/**`
   - screenshot each affected route at **390×844** and **1280×800**
   - read the console; any new error is a failure
   - tab through any form you touched and confirm the focus ring is visible
   - fix what's wrong and repeat; say which screenshots you checked
5. `npm run build` must pass (it runs `tsc`).

## Layout

- `src/main.tsx` routes and `Layout` (header/footer). `src/pages/` one file per route.
- `src/components/` app components (`StatusBadge`, `JobTimeline`, `Field`, ...); `src/components/ui/` shadcn components.
- `src/api.ts` is the only place that talks to the API.
