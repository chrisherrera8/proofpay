import { useEffect, useRef, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";
import { CalendarDays, Camera, ChevronLeft, CircleCheck, CircleMinus, CircleX, Clock, Loader2, Plus, RotateCcw, Trash2, Unlock, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Page } from "@/components/layout";
import { JobTimeline } from "@/components/job-timeline";
import { SectionCard } from "@/components/section-card";
import { ErrorAlert, PageSkeleton } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import { formatDay, formatMoney, formatWhen } from "@/lib/format";
import { cn } from "@/lib/utils";
import { tierById } from "../tiers";
import type { CleanerJobsContext } from "./CleanerJobs";
import { deleteJob, deletePhoto, getJob, Job, listPhotos, Photo, photoUrl, settleJob, submitJob, uploadPhoto, verifyJob } from "../api";
import { resizeImage } from "../resize";

const MAX_PER_KIND = 4;

function PhotoSlot({ jobId, kind, photos, locked, onChange, onError }: {
  jobId: string;
  kind: Photo["kind"];
  photos: Photo[];
  locked: boolean;
  onChange: () => void;
  onError: (m: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const mine = photos.filter((p) => p.kind === kind);

  async function pick(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    onError("");
    try {
      for (const f of Array.from(files).slice(0, MAX_PER_KIND - mine.length)) {
        await uploadPhoto(jobId, kind, await resizeImage(f));
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
      onChange();
    }
  }

  async function remove(id: number) {
    try {
      await deletePhoto(jobId, id);
    } catch (e) {
      onError((e as Error).message);
    }
    onChange();
  }

  const label = kind === "before" ? "Before" : "After";
  const canAdd = !locked && mine.length < MAX_PER_KIND;
  return (
    <SectionCard
      title={`${label} photos`}
      action={<span className="text-sm text-muted-foreground tabular-nums">{mine.length}/{MAX_PER_KIND}</span>}
    >
      <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4">
        {mine.map((p, n) => (
          <li key={p.id} className="relative aspect-square">
            <img src={photoUrl(jobId, p.id)} alt={`${label} photo ${n + 1}`} className="size-full rounded-lg border object-cover" />
            {!locked && (
              <button
                type="button"
                aria-label={`Remove ${kind} photo ${n + 1}`}
                onClick={() => remove(p.id)}
                className="absolute -top-2 -right-2 flex size-8 items-center justify-center rounded-full border bg-card text-destructive shadow-xs outline-none hover:bg-danger focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <X className="size-4" aria-hidden />
              </button>
            )}
          </li>
        ))}
        {canAdd && (
          <li className="aspect-square">
            <input ref={input} type="file" accept="image/*" capture="environment" multiple hidden
              onChange={(e) => pick(e.target.files)} />
            <button
              type="button"
              disabled={busy}
              onClick={() => input.current?.click()}
              className="flex size-full flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed border-input/60 bg-muted/50 p-2 text-center text-xs font-medium text-muted-foreground transition-colors outline-none hover:border-primary hover:bg-accent hover:text-accent-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-wait"
            >
              {busy ? <Loader2 className="size-5 animate-spin" aria-hidden /> : mine.length ? <Plus className="size-5" aria-hidden /> : <Camera className="size-5" aria-hidden />}
              {busy ? "Uploading…" : mine.length ? "Add photo" : `Take ${kind} photo`}
            </button>
          </li>
        )}
      </ul>
      {mine.length === 0 && locked && <p className="text-sm text-muted-foreground">No photos.</p>}
    </SectionCard>
  );
}

// Statuses a job passes through once it is cleared for payment.
const PAYMENT_STATUSES = ["RELEASED", "CAPTURED", "PAID_OUT"];

// What each policy outcome means for the job's status. The reasons are only shown while the job is still
// in a state the decision put it in (after an admin approves, the stored decision is stale).
const DECISION_VIEW = {
  auto_release: { statuses: PAYMENT_STATUSES, title: "Released for payment", icon: Unlock, tone: "success" },
  needs_approval: { statuses: ["PENDING_APPROVAL"], title: "Waiting for a manager to approve", icon: Clock, tone: "warning" },
  reject: { statuses: ["REJECTED"], title: "Re-clean needed", icon: RotateCcw, tone: "danger" },
} as const;

function DecisionPanel({ job }: { job: Job }) {
  const d = job.decision;
  if (!d) return null;
  const view = DECISION_VIEW[d.outcome];
  if (!(view.statuses as readonly string[]).includes(job.status)) return null;
  const Icon = view.icon;
  return (
    <div role="status" className={cn("rounded-xl border p-5", TONE_PANEL[view.tone])}>
      <p className="flex items-center gap-2 font-semibold"><Icon className="size-5" aria-hidden /> {view.title}</p>
      <ul className="mt-2 grid list-disc gap-1 pl-7 text-sm">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
    </div>
  );
}

const TONE_PANEL = {
  success: "border-success-foreground/20 bg-success text-success-foreground",
  warning: "border-warning-foreground/20 bg-warning text-warning-foreground",
  danger: "border-destructive/20 bg-danger text-destructive",
} as const;

// Retry makes sense until the payout has failed: settle does nothing for a FAILED payout.
function canRetryPayment(job: Job): boolean {
  if (job.status === "RELEASED") return true;
  return job.status === "CAPTURED" && job.payout?.status !== "FAILED";
}

function PaymentPanel({ job, working, onRetry }: { job: Job; working: boolean; onRetry: () => void }) {
  if (!PAYMENT_STATUSES.includes(job.status)) return null;
  const failed = job.status === "CAPTURED" && job.payout?.status === "FAILED";
  let title: string;
  let detail: string;
  if (job.status === "PAID_OUT") {
    title = `${formatMoney(job.payout?.amount ?? job.amount, job.currency)} paid to your PayPal`;
    detail = "The payout has arrived. Nice work.";
  } else if (failed) {
    title = "Payout failed";
    detail = "PayPal couldn't send your payout. It needs a look from the team.";
  } else if (job.status === "CAPTURED") {
    title = "Payout on the way";
    detail = "The customer has been charged; PayPal usually sends the payout within a minute.";
  } else {
    title = "Payment not collected yet";
    detail = "The work is approved but the customer's payment hasn't been captured.";
  }
  return (
    <SectionCard title="Payment">
      <div role="status" className="flex items-start gap-3">
        <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg", job.status === "PAID_OUT" ? "bg-success text-success-foreground" : failed ? "bg-danger text-destructive" : "bg-accent text-accent-foreground")}>
          {job.status === "PAID_OUT" ? <CircleCheck className="size-5" aria-hidden /> : failed ? <CircleX className="size-5" aria-hidden /> : <Clock className="size-5" aria-hidden />}
        </span>
        <div>
          <p className="font-semibold tabular-nums">{title}</p>
          <p className="text-sm text-muted-foreground">{detail}</p>
        </div>
      </div>
      {canRetryPayment(job) && (
        <Button variant="outline" size="lg" className="mt-4 h-11 w-full sm:w-auto" disabled={working} onClick={onRetry}>
          {working ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCcw aria-hidden />}
          {working ? "Retrying…" : "Retry payment"}
        </Button>
      )}
    </SectionCard>
  );
}

export default function CleanerJob() {
  const { jobId } = useParams() as { jobId: string };
  const [job, setJob] = useState<Job | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const parent = useOutletContext<CleanerJobsContext | null>();

  // Tracks the job on screen so a slow response for a previous job is dropped.
  const currentJobId = useRef(jobId);
  currentJobId.current = jobId;

  const refresh = () => {
    const requested = jobId;
    return Promise.all([getJob(requested), listPhotos(requested)])
      .then(([j, p]) => {
        if (currentJobId.current !== requested) return;
        setJob(j);
        setPhotos(p);
      })
      .catch((e) => {
        if (currentJobId.current === requested) setError(e.message);
      });
  };

  useEffect(() => { refresh(); }, [jobId]);

  async function run(fn: (id: string) => Promise<Job>) {
    setWorking(true);
    setError("");
    try {
      setJob(await fn(jobId));
    } catch (e) {
      setError((e as Error).message);
      refresh(); // the job may now be SUBMITTED (vision failed): show the retry button
    } finally {
      setWorking(false);
    }
  }

  async function remove() {
    if (!window.confirm("Delete this job? This permanently removes it and its photos.")) return;
    setWorking(true);
    setError("");
    try {
      await deleteJob(jobId);
      parent?.onDeleted(jobId);
    } catch (e) {
      setError((e as Error).message);
      setWorking(false);
    }
  }

  if (!job) return error ? <Page flush><ErrorAlert message={error} /></Page> : <PageSkeleton label="Loading job" />;

  const editable = job.status === "AUTHORIZED" || job.status === "REJECTED";
  const ready = photos.some((p) => p.kind === "before") && photos.some((p) => p.kind === "after");
  const v = job.verification;

  return (
    <div className="w-full py-8 sm:py-12 lg:py-8">
      <Link to="/cleaner" className="inline-flex lg:hidden items-center gap-1 rounded text-sm text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none">
        <ChevronLeft className="size-4" aria-hidden /> All jobs
      </Link>
      <header className="mt-3 rounded-2xl border bg-card p-6 shadow-xs lg:mt-0 sm:p-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-medium text-muted-foreground">
            {tierById(job.service_type)?.name ?? job.service_type}
          </p>
          <StatusBadge status={job.status} />
        </div>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">{job.address}</h1>
        {job.strict_check && (
          <p className="mt-3 rounded-lg bg-warning px-3 py-2 text-sm text-warning-foreground">
            Strict check: every checklist item must be clearly visible in your after photos, or it counts as failed.
          </p>
        )}
        <dl className="mt-6 grid gap-4 border-t pt-5 sm:grid-cols-2">
          <div>
            <dt className="text-sm text-muted-foreground">Service date</dt>
            <dd className="mt-1 flex items-center gap-1.5 font-medium">
              <CalendarDays className="size-4 text-muted-foreground" aria-hidden />
              {job.service_date ? formatDay(job.service_date) : formatWhen(job.scheduled_at)}
            </dd>
          </div>
          <div>
            <dt className="text-sm text-muted-foreground">Job value</dt>
            <dd className="mt-1 font-medium tabular-nums">{formatMoney(job.amount, job.currency)}</dd>
          </div>
        </dl>
      </header>

      <div className="mt-6 grid items-start gap-6 xl:grid-cols-3">
      <div className="grid gap-6 xl:col-span-2">
        <DecisionPanel job={job} />
        <PaymentPanel job={job} working={working} onRetry={() => run(settleJob)} />

        {v && (
          <SectionCard
            title={v.results.overall_pass ? "Checks passed" : "Some items need attention"}
            action={<span className="text-sm text-muted-foreground tabular-nums">Score {v.score ?? "–"}</span>}
          >
            <ul className="grid divide-y">
              {v.results.items.map((i) => {
                const Icon = !i.visible ? CircleMinus : i.pass ? CircleCheck : CircleX;
                const verdict = !i.visible ? "Not visible" : i.pass ? "Passed" : "Failed";
                return (
                  <li key={i.item} className="flex gap-3 py-3 first:pt-0 last:pb-0">
                    <Icon className={cn("mt-0.5 size-5 shrink-0", !i.visible ? "text-muted-foreground" : i.pass ? "text-success-foreground" : "text-destructive")} aria-hidden />
                    <div>
                      <p className="text-sm font-medium">{i.item} <span className="sr-only">: {verdict}</span></p>
                      <p className="text-sm text-muted-foreground">{i.visible ? i.note : "Not visible in the after photos"}</p>
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">Checked by {v.model}</p>
          </SectionCard>
        )}

        <PhotoSlot jobId={jobId} kind="before" photos={photos} locked={!editable} onChange={refresh} onError={setError} />
        <PhotoSlot jobId={jobId} kind="after" photos={photos} locked={!editable} onChange={refresh} onError={setError} />

        {error && <ErrorAlert message={error} />}

        {(editable || job.status === "SUBMITTED") && (
          <div>
            {editable ? (
              <Button size="lg" className="h-12 w-full text-base" disabled={!ready || working} onClick={() => run(submitJob)}>
                {working && <Loader2 className="animate-spin" aria-hidden />}
                {working ? "Checking the photos…" : "Submit for verification"}
              </Button>
            ) : (
              <Button size="lg" className="h-12 w-full text-base" disabled={working} onClick={() => run(verifyJob)}>
                {working ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCcw aria-hidden />}
                {working ? "Checking the photos…" : "Retry verification"}
              </Button>
            )}
            {editable && !ready && <p className="mt-2 text-center text-sm text-muted-foreground">Add at least one before and one after photo.</p>}
          </div>
        )}

      </div>
      <aside className="grid gap-6 xl:sticky xl:top-0">
        <SectionCard title="Checklist">
          {editable && <p className="-mt-2 mb-3 text-sm text-muted-foreground">Take a before photo, clean, then take after photos that show each item below.</p>}
          <ul className="grid gap-2 text-sm">
            {job.checklist_items.map((i) => (
              <li key={i.id} className="flex items-center gap-3">
                <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                {i.label}
                {i.required && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">Required</span>}
              </li>
            ))}
          </ul>
        </SectionCard>
        <SectionCard title="Progress">
          <JobTimeline status={job.status} />
        </SectionCard>
        {(job.status === "BOOKED" || job.status === "PAID_OUT") && (
          <Button variant="outline" className="h-11 w-full text-destructive" disabled={working} onClick={remove}>
            <Trash2 aria-hidden /> Delete job
          </Button>
        )}
      </aside>
      </div>
    </div>
  );
}
