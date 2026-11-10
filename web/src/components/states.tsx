import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Page } from "@/components/layout";

// Shared loading and error screens for the narrow pages (design.md: skeletons, never a bare "Loading…").
export function PageSkeleton({ label = "Loading" }: { label?: string }) {
  return (
    <Page>
      <div role="status" aria-label={label} className="grid gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="mt-4 h-40 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    </Page>
  );
}

export function ErrorAlert({ message, className }: { message: string; className?: string }) {
  return (
    <Alert variant="destructive" className={className}>
      <AlertCircle aria-hidden />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
