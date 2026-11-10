import { Check, Clock, X } from "lucide-react";
import { cn } from "@/lib/utils";

const STEPS = [
  { title: "Booked", detail: "Payment held on PayPal, not charged" },
  { title: "Photos submitted", detail: "Before and after photos uploaded" },
  { title: "Work verified", detail: "Photos checked against the checklist" },
  { title: "Customer charged", detail: "Held payment captured" },
  { title: "Cleaner paid", detail: "Payout sent to the cleaner's PayPal" },
];

// Where each status sits on the timeline, and whether that step is stuck.
const POSITION: Record<string, { step: number; state?: "warning" | "error" }> = {
  BOOKED: { step: 0 },
  AUTHORIZED: { step: 1 },
  REJECTED: { step: 1, state: "error" },
  SUBMITTED: { step: 2 },
  VERIFIED: { step: 2 },
  PENDING_APPROVAL: { step: 2, state: "warning" },
  RELEASED: { step: 3 },
  CAPTURED: { step: 4 },
  PAID_OUT: { step: 5 },
};

const STUCK_DETAIL = { error: "Some items need a re-clean", warning: "Waiting for a manager to approve" };

export function JobTimeline({ status }: { status: string }) {
  const pos = POSITION[status] ?? { step: 0 };
  return (
    <ol className="grid gap-0">
      {STEPS.map((s, i) => {
        const done = i < pos.step;
        const current = i === pos.step;
        const stuck = current ? pos.state : undefined;
        return (
          <li key={s.title} className="relative flex gap-3 pb-5 last:pb-0" aria-current={current ? "step" : undefined}>
            {i < STEPS.length - 1 && (
              <span aria-hidden className={cn("absolute top-7 bottom-0 left-3.5 w-px -translate-x-1/2", done ? "bg-primary" : "bg-border")} />
            )}
            <span
              aria-hidden
              className={cn(
                "relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                done && "border-primary bg-primary text-primary-foreground",
                current && !stuck && "border-primary bg-card text-primary ring-4 ring-accent",
                stuck === "error" && "border-destructive bg-danger text-destructive",
                stuck === "warning" && "border-warning-foreground bg-warning text-warning-foreground",
                !done && !current && "border-border bg-card text-muted-foreground",
              )}
            >
              {done ? <Check className="size-4" /> : stuck === "error" ? <X className="size-4" /> : stuck === "warning" ? <Clock className="size-4" /> : i + 1}
            </span>
            <div className="pt-0.5">
              <p className={cn("text-sm font-medium", !done && !current && "text-muted-foreground")}>
                {s.title}
                <span className="sr-only">{done ? " (done)" : current ? " (current step)" : " (not started)"}</span>
              </p>
              <p className={cn("text-sm text-muted-foreground", stuck === "error" && "text-destructive", stuck === "warning" && "text-warning-foreground")}>
                {stuck ? STUCK_DETAIL[stuck] : s.detail}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
