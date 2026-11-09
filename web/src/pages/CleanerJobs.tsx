import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Job, listJobs } from "../api";
import { tierById } from "../tiers";

export default function CleanerJobs() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // AUTHORIZED = paid-for and waiting for the cleaner; REJECTED = needs a re-clean.
    Promise.all([listJobs("AUTHORIZED"), listJobs("REJECTED")])
      .then(([a, r]) => setJobs([...r, ...a]))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <section className="section narrow">
      <h2>Cleaner jobs</h2>
      {error && <p className="error">{error}</p>}
      {!jobs && !error && <p>Loading…</p>}
      {jobs?.length === 0 && <p className="muted">No jobs are waiting for photos.</p>}
      <div className="job-list">
        {jobs?.map((j) => (
          <Link key={j.id} to={`/cleaner/${j.id}`} className="card job-row">
            <strong>{tierById(j.service_type)?.name ?? j.service_type}</strong>
            <span>{j.address}</span>
            <span className="muted">
              {new Date(j.scheduled_at).toLocaleString()} · {j.status === "REJECTED" ? "Re-clean needed" : "Ready"}
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
