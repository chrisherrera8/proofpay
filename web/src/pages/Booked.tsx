import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getJob, Job } from "../api";
import { tierById } from "../tiers";

export default function Booked() {
  const { jobId } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (jobId) getJob(jobId).then(setJob).catch((e) => setError(e.message));
  }, [jobId]);

  if (error) return <section className="section narrow"><p className="error">{error}</p></section>;
  if (!job) return <section className="section narrow"><p>Loading…</p></section>;

  return (
    <section className="section narrow">
      <h2>Booked! 🎉</h2>
      <p>Thanks, {job.customer_name}. Your {tierById(job.service_type)?.name ?? job.service_type} is scheduled for{" "}
        <strong>{new Date(job.scheduled_at).toLocaleString()}</strong> at {job.address}.</p>
      <p>Status: <strong>{job.status}</strong> · ${job.amount} {job.currency} authorized, not yet charged.</p>
      <h3>Checklist</h3>
      <ul>{job.checklist_items.map((i) => <li key={i.id}>{i.label}</li>)}</ul>
      <Link to="/" className="btn">Back to home</Link>
    </section>
  );
}
