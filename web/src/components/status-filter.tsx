import { STATUS } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import type { StatusCount } from "@/lib/job-sections";

const CHIP =
  "inline-flex h-11 items-center gap-1.5 rounded-full border px-4 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50";

// Single-select status chips: "All" plus one per status present. `value` null means All.
export function StatusFilter({ counts, value, onChange }: {
  counts: StatusCount[];
  value: string | null;
  onChange: (status: string | null) => void;
}) {
  const total = counts.reduce((n, c) => n + c.count, 0);
  const chips = [{ status: null as string | null, label: "All", count: total }].concat(
    counts.map((c) => ({ status: c.status, label: STATUS[c.status]?.label ?? c.status.toLowerCase().replace(/_/g, " "), count: c.count })),
  );
  return (
    <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
      {chips.map((c) => {
        const pressed = c.status === value;
        return (
          <button
            key={c.status ?? "all"}
            type="button"
            aria-pressed={pressed}
            onClick={() => onChange(c.status)}
            className={cn(CHIP, pressed ? "border-primary/40 bg-accent text-accent-foreground" : "bg-card hover:border-primary/40")}
          >
            {c.label}{" "}
            <span className="tabular-nums text-muted-foreground">{c.count}</span>
          </button>
        );
      })}
    </div>
  );
}
