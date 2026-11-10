import { cn } from "@/lib/utils";

// A titled card section. Pages stack these; never nest one inside another.
export function SectionCard({ title, action, children, className }: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const id = `sec-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={id} className={cn("rounded-xl border bg-card p-5 shadow-xs sm:p-6", className)}>
      <div className="flex items-center justify-between gap-3">
        <h2 id={id} className="font-semibold">{title}</h2>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}
