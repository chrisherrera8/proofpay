import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { CalendarDays, ChevronRight, Inbox } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Page } from "@/components/layout";
import { ErrorAlert } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { clearCleanerId, getCleanerId } from "@/lib/cleaner-session";
import { formatDay } from "@/lib/format";
import { ApiError, Cleaner, getCleaner, Job, listJobs } from "../api";
import { tierById } from "../tiers";

export default function CleanerJobs() {
  const cleanerId = getCleanerId();
  const [cleaner, setCleaner] = useState<Cleaner | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    if (!cleanerId) return;
    // An expired cleaner is a 404: forget the id and flag it. The no-id redirect below carries the flag,
    // so it can't be overtaken by another re-render (StrictMode re-runs this effect in dev).
    getCleaner(cleanerId)
      .then(setCleaner)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) {
          clearCleanerId();
          setExpired(true);
        } else {
          setError(e.message);
        }
      });
    // AUTHORIZED = paid-for and waiting for the cleaner; REJECTED = needs a re-clean.
    Promise.all([listJobs("AUTHORIZED", cleanerId), listJobs("REJECTED", cleanerId)])
      .then(([a, r]) => setJobs([...r, ...a]))
      .catch((e) => setError(e.message));
  }, [cleanerId]);

  if (!cleanerId) return <Navigate to="/cleaner/signup" replace state={expired ? { expired: true } : undefined} />;

  return (
    <Page>
      <h1 className="text-3xl font-semibold">{cleaner ? `${cleaner.name}'s jobs` : "Your jobs"}</h1>
      <p className="mt-2 text-muted-foreground">Jobs waiting for before and after photos. Re-cleans are listed first.</p>

      <div className="mt-8">
        {error && <ErrorAlert message={error} />}
        {!jobs && !error && (
          <div role="status" aria-label="Loading jobs" className="grid gap-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}
          </div>
        )}
        {jobs?.length === 0 && (
          <div className="flex flex-col items-center rounded-xl border border-dashed bg-card px-6 py-12 text-center">
            <Inbox className="size-8 text-muted-foreground" aria-hidden />
            <p className="mt-3 font-medium">No jobs waiting</p>
            <p className="mt-1 text-sm text-muted-foreground">New bookings show up here once the customer's payment is held.</p>
          </div>
        )}
        {!!jobs?.length && (
          <ul className="grid gap-3">
            {jobs.map((j) => (
              <li key={j.id}>
                <Link
                  to={`/cleaner/${j.id}`}
                  className="group flex items-center gap-4 rounded-xl border bg-card p-4 shadow-xs transition-colors outline-none hover:border-primary/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 sm:p-5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{tierById(j.service_type)?.name ?? j.service_type}</span>
                      <StatusBadge status={j.status} />
                    </div>
                    <p className="mt-1 truncate text-sm">{j.address}</p>
                    <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
                      <CalendarDays className="size-4" aria-hidden />
                      {j.service_date ? formatDay(j.service_date) : "Date to be confirmed"}
                    </p>
                  </div>
                  <ChevronRight className="size-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="mt-8 text-sm text-muted-foreground">
        Not you?{" "}
        <Link
          to="/cleaner/signup"
          onClick={clearCleanerId}
          className="rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          Switch cleaner
        </Link>
      </p>
    </Page>
  );
}
