import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CalendarDays, ChevronRight, Inbox } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { ErrorAlert } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { StatusFilter } from "@/components/status-filter";
import { clearCleanerId, getCleanerId } from "@/lib/cleaner-session";
import { formatDay } from "@/lib/format";
import { groupJobs, statusCounts } from "@/lib/job-sections";
import { ApiError, Cleaner, getCleaner, Job, listJobs } from "../api";
import { tierById } from "../tiers";

const JOB_LIMIT = 200;

// Below lg the list and the open job are alternate screens, so auto-opening a job would hide the list.
const isSplitView = () => window.matchMedia("(min-width: 1024px)").matches;

function JobRow({ job: j, active }: { job: Job; active: boolean }) {
  const location = useLocation();
  return (
    <li>
      <Link
        to={{ pathname: `/cleaner/${j.id}`, search: location.search }}
        aria-current={active ? "page" : undefined}
        className={cn(
          "group flex items-center gap-4 rounded-xl border bg-card p-4 shadow-xs transition-colors outline-none hover:border-primary/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 sm:p-5",
          active && "border-primary bg-primary/5",
        )}
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
  );
}

export default function CleanerJobs() {
  const cleanerId = getCleanerId();
  const [cleaner, setCleaner] = useState<Cleaner | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const { jobId } = useParams();
  const location = useLocation();
  const open = !!jobId;
  const navigate = useNavigate();

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
    listJobs(cleanerId, { limit: JOB_LIMIT })
      .then(setJobs)
      .catch((e) => setError(e.message));
  }, [cleanerId]);

  const counts = useMemo(() => statusCounts(jobs ?? []), [jobs]);
  // An unknown ?status= falls back to All.
  const requested = searchParams.get("status");
  const filter = requested && counts.some((c) => c.status === requested) ? requested : null;
  const groups = useMemo(() => groupJobs(jobs ?? [], filter), [jobs, filter]);

  // Side by side, the detail pane should always show a job: open the first one on load and on every filter change.
  const firstId = groups[0]?.jobs[0]?.id;
  useEffect(() => {
    if (!jobId && firstId && isSplitView()) {
      navigate({ pathname: `/cleaner/${firstId}`, search: location.search }, { replace: true });
    }
  }, [jobId, firstId, navigate, location.search]);

  const setFilter = (status: string | null) => {
    const search = status ? `?${new URLSearchParams({ status })}` : "";
    const first = groupJobs(jobs ?? [], status)[0]?.jobs[0];
    if (first && isSplitView()) {
      navigate({ pathname: `/cleaner/${first.id}`, search }, { replace: true });
    } else {
      setSearchParams(status ? { status } : {}, { replace: true });
    }
  };

  if (!cleanerId) return <Navigate to="/cleaner/signup" replace state={expired ? { expired: true } : undefined} />;

  return (
    // The list stays mounted while jobs open beside it, so it keeps its scroll, filter and data.
    // Side by side the page fills the viewport below the sticky header (h-16) and each pane scrolls on its own.
    <div className="flex w-full lg:h-[calc(100dvh-4rem)]">
      <div className={cn("w-full shrink-0 px-4 py-8 sm:px-6 sm:py-12 lg:w-112 lg:overflow-y-auto lg:border-r lg:py-8", open && "hidden lg:block")}>
      <h1 className="text-3xl font-semibold">{cleaner ? `${cleaner.name}'s jobs` : "Your jobs"}</h1>
      <p className="mt-2 text-muted-foreground">All your jobs. Anything that needs your attention is listed first.</p>

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
            <p className="mt-3 font-medium">No jobs yet</p>
            <p className="mt-1 text-sm text-muted-foreground">New bookings show up here once the customer's payment is held.</p>
          </div>
        )}
        {!!jobs?.length && (
          <div className="grid gap-8">
            <StatusFilter counts={counts} value={filter} onChange={setFilter} />
            {groups.map(({ section, jobs: rows }) => (
              <section key={section.id} aria-labelledby={`jobs-${section.id}`}>
                <h2 id={`jobs-${section.id}`} className="font-semibold">
                  {section.title} <span className="font-normal text-muted-foreground tabular-nums">{rows.length}</span>
                </h2>
                <ul className="mt-3 grid gap-3">
                  {rows.map((j) => <JobRow key={j.id} job={j} active={j.id === jobId} />)}
                </ul>
              </section>
            ))}
            {jobs.length >= JOB_LIMIT && (
              <p className="text-sm text-muted-foreground">Showing the latest {JOB_LIMIT} jobs.</p>
            )}
          </div>
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
      </div>
      <div
        className={cn(
          "min-w-0 overflow-x-hidden px-4 transition-[opacity] duration-300 ease-out motion-reduce:transition-none sm:px-6 lg:overflow-y-auto lg:px-10",
          open ? "w-full flex-1 opacity-100" : "w-0 flex-none px-0 opacity-0 sm:px-0 lg:px-0",
        )}
      >
        {/* Keyed so switching jobs never flashes the previous job's data. */}
        <Outlet key={jobId} />
      </div>
    </div>
  );
}
