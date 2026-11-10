import * as React from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// Label + input + error, wired for screen readers (design.md: every input has a label, errors use aria-describedby).
export function Field({ id, label, error, hint, className, ...props }: React.ComponentProps<typeof Input> & {
  id: string;
  label: string;
  error?: string;
  hint?: string;
}) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-err`].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("grid gap-2", className)}>
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} className="h-11" aria-invalid={!!error} aria-describedby={describedBy} {...props} />
      {hint && !error && <p id={`${id}-hint`} className="text-sm text-muted-foreground">{hint}</p>}
      {error && <p id={`${id}-err`} className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
