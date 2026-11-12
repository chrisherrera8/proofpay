import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CalendarDays, CircleCheck, MapPin, UserRound, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Page } from "@/components/layout";
import { JobTimeline } from "@/components/job-timeline";
import { SectionCard } from "@/components/section-card";
import { ErrorAlert, PageSkeleton } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { formatDay, formatMoney, formatWhen } from "@/lib/format";
import { getJob, Job } from "../api";
import { tierById } from "../tiers";

export default function Booked() {
  const { jobId } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (jobId) getJob(jobId).then(setJob).catch((e) => setError(e.message));
  }, [jobId]);

  if (error) return <Page><ErrorAlert message={error} /></Page>;
  if (!job) return <PageSkeleton label="Loading your booking" />;

  const service = tierById(job.service_type)?.name ?? job.service_type;

  return (
    <Page>
      <div className="flex flex-col items-start gap-4">
        <span className="flex size-12 items-center justify-center rounded-full bg-success text-success-foreground">
          <CircleCheck className="size-6" aria-hidden />
        </span>
        <div>
          <h1 className="text-3xl font-semibold">You're booked</h1>
          <p className="mt-2 text-muted-foreground">
            Thanks, {job.customer_name}. Here's your booking and what happens next.
          </p>
        </div>
      </div>

      <div className="mt-8 grid gap-6">
        <SectionCard title={service} action={<StatusBadge status={job.status} />}>
          <dl className="grid gap-3 text-sm">
            <div className="flex gap-3">
              <dt><CalendarDays className="size-4 text-muted-foreground" aria-label="When" /></dt>
              <dd>{job.service_date ? formatDay(job.service_date) : formatWhen(job.scheduled_at)}</dd>
            </div>
            <div className="flex gap-3">
              <dt><UserRound className="size-4 text-muted-foreground" aria-label="Cleaner" /></dt>
              <dd>{job.cleaner_name ?? "Your cleaner (their demo data has been deleted)"}</dd>
            </div>
            <div className="flex gap-3">
              <dt><MapPin className="size-4 text-muted-foreground" aria-label="Where" /></dt>
              <dd>{job.address}</dd>
            </div>
            <div className="flex gap-3">
              <dt><Wallet className="size-4 text-muted-foreground" aria-label="Payment" /></dt>
              <dd><span className="font-medium tabular-nums">{formatMoney(job.amount, job.currency)}</span> held on PayPal, not charged yet</dd>
            </div>
          </dl>
        </SectionCard>

        <SectionCard title="What happens next">
          <JobTimeline status={job.status} />
        </SectionCard>

        <SectionCard title="Your checklist">
          <p className="-mt-2 mb-3 text-sm text-muted-foreground">Your cleaner photographs each of these before you're charged.</p>
          <ul className="grid gap-2 text-sm">
            {job.checklist_items.map((i) => (
              <li key={i.id} className="flex items-center gap-3">
                <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                {i.label}
              </li>
            ))}
          </ul>
        </SectionCard>
      </div>

      <Button asChild variant="outline" size="lg" className="mt-8 h-11 w-full sm:w-auto">
        <Link to="/">Back to home</Link>
      </Button>
    </Page>
  );
}
