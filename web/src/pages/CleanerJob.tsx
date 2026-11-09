import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { deletePhoto, getJob, Job, listPhotos, Photo, photoUrl, submitJob, uploadPhoto, verifyJob } from "../api";
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

  return (
    <div className="photo-slot">
      <h3>{kind === "before" ? "Before" : "After"} photos</h3>
      <div className="thumbs">
        {mine.map((p) => (
          <div key={p.id} className="thumb">
            <img src={photoUrl(jobId, p.id)} alt={`${kind} photo`} />
            {!locked && <button type="button" aria-label="Remove photo" onClick={() => remove(p.id)}>×</button>}
          </div>
        ))}
      </div>
      {!locked && mine.length < MAX_PER_KIND && (
        <>
          <input ref={input} type="file" accept="image/*" capture="environment" multiple hidden
            onChange={(e) => pick(e.target.files)} />
          <button type="button" className="btn small" disabled={busy} onClick={() => input.current?.click()}>
            {busy ? "Uploading…" : mine.length ? "Add another" : `Take or choose ${kind} photo`}
          </button>
        </>
      )}
    </div>
  );
}

// What each policy outcome means for the job's status. The reasons are only shown while the job is still
// in the state the decision put it in (after an admin approves, the stored decision is stale).
const DECISION_VIEW = {
  auto_release: { status: "RELEASED", title: "✅ Released" },
  needs_approval: { status: "PENDING_APPROVAL", title: "⏳ Waiting for approval" },
  reject: { status: "REJECTED", title: "❌ Rejected: please re-clean" },
} as const;

function DecisionPanel({ job }: { job: Job }) {
  const d = job.decision;
  if (!d) return null;
  const view = DECISION_VIEW[d.outcome];
  if (job.status !== view.status) return null;
  return (
    <div className="result" role="status">
      <h3>{view.title}</h3>
      <ul>{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
    </div>
  );
}

export default function CleanerJob() {
  const { jobId } = useParams() as { jobId: string };
  const [job, setJob] = useState<Job | null>(null);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

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

  if (!job) return <section className="section narrow">{error ? <p className="error">{error}</p> : <p>Loading…</p>}</section>;

  const editable = job.status === "AUTHORIZED" || job.status === "REJECTED";
  const ready = photos.some((p) => p.kind === "before") && photos.some((p) => p.kind === "after");
  const v = job.verification;

  return (
    <section className="section narrow">
      <Link to="/cleaner" className="muted">← All jobs</Link>
      <h2>{job.address}</h2>
      <p className="muted">{new Date(job.scheduled_at).toLocaleString()} · Status: <strong>{job.status}</strong></p>

      <h3>Checklist</h3>
      <ul>{job.checklist_items.map((i) => <li key={i.id}>{i.label}</li>)}</ul>

      {editable && <p className="muted">Take a before photo, clean, then take an after photo that shows the rooms on the checklist.</p>}
      <PhotoSlot jobId={jobId} kind="before" photos={photos} locked={!editable} onChange={refresh} onError={setError} />
      <PhotoSlot jobId={jobId} kind="after" photos={photos} locked={!editable} onChange={refresh} onError={setError} />

      {error && <p className="error" role="alert">{error}</p>}

      {editable && (
        <button className="btn" disabled={!ready || working} onClick={() => run(submitJob)}>
          {working ? "Checking the photos…" : "Submit for verification"}
        </button>
      )}
      {job.status === "SUBMITTED" && (
        <button className="btn" disabled={working} onClick={() => run(verifyJob)}>
          {working ? "Checking the photos…" : "Retry verification"}
        </button>
      )}

      <DecisionPanel job={job} />

      {v && (
        <div className="result">
          <h3>{v.results.overall_pass ? "✅ Checks passed" : "⚠️ Some items need attention"}</h3>
          <p className="muted">Score {v.score} · {v.model}</p>
          <ul className="verdicts">
            {v.results.items.map((i) => (
              <li key={i.item}>
                <strong>{!i.visible ? "➖" : i.pass ? "✅" : "❌"} {i.item}</strong>
                <span className="muted"> {i.visible ? i.note : "Not visible in the after photos"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
