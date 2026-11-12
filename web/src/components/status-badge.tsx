import type { LucideIcon } from "lucide-react";
import { BadgeCheck, CalendarCheck, Clock, CircleX, CreditCard, Lock, RotateCcw, ShieldCheck, Unlock, Upload } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

// The one place a job status turns into words, color and an icon (design.md: never show raw statuses).
export const STATUS: Record<string, { label: string; tone: Tone; icon: LucideIcon }> = {
  BOOKED: { label: "Booked", tone: "neutral", icon: CalendarCheck },
  AUTHORIZED: { label: "Payment held", tone: "info", icon: Lock },
  SUBMITTED: { label: "Photos submitted", tone: "neutral", icon: Upload },
  VERIFIED: { label: "Verified", tone: "info", icon: ShieldCheck },
  PENDING_APPROVAL: { label: "Awaiting approval", tone: "warning", icon: Clock },
  REJECTED: { label: "Re-clean needed", tone: "danger", icon: RotateCcw },
  RELEASED: { label: "Released for payment", tone: "success", icon: Unlock },
  CAPTURED: { label: "Payment captured", tone: "success", icon: CreditCard },
  PAYOUT_FAILED: { label: "Payout failed", tone: "danger", icon: CircleX },
  PAID_OUT: { label: "Paid out", tone: "success", icon: BadgeCheck },
};

const TONE: Record<Tone, string> = {
  neutral: "bg-muted text-foreground border-border",
  info: "bg-accent text-accent-foreground border-primary/15",
  success: "bg-success text-success-foreground border-success-foreground/15",
  warning: "bg-warning text-warning-foreground border-warning-foreground/15",
  danger: "bg-danger text-destructive border-destructive/15",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = STATUS[status] ?? { label: status.toLowerCase().replace(/_/g, " "), tone: "neutral" as Tone, icon: Clock };
  const Icon = s.icon;
  return (
    <span className={cn("inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium whitespace-nowrap", TONE[s.tone], className)}>
      <Icon className="size-3.5" aria-hidden />
      {s.label}
    </span>
  );
}
