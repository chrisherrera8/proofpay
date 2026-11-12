import type { Job } from "../api";

export interface JobSection {
  id: string;
  title: string;
  statuses: string[];
}

// Grouped by what the cleaner should do. Order matters: sections, and statuses within them, render in this order.
export const JOB_SECTIONS: JobSection[] = [
  { id: "attention", title: "Needs your attention", statuses: ["REJECTED", "AUTHORIZED"] },
  { id: "review", title: "In review", statuses: ["SUBMITTED", "VERIFIED", "PENDING_APPROVAL"] },
  { id: "payment", title: "Payment", statuses: ["RELEASED", "CAPTURED"] },
  { id: "completed", title: "Completed", statuses: ["PAID_OUT"] },
  { id: "upcoming", title: "Upcoming", statuses: ["BOOKED"] },
];

// A status the backend adds later still shows up here instead of vanishing.
const OTHER: JobSection = { id: "other", title: "Other", statuses: [] };

const KNOWN = JOB_SECTIONS.flatMap((s) => s.statuses);

function sectionFor(status: string): JobSection {
  return JOB_SECTIONS.find((s) => s.statuses.includes(status)) ?? OTHER;
}

// Position of a status in the overall section/status order; unknown statuses go last.
function statusRank(status: string): number {
  const i = KNOWN.indexOf(status);
  return i === -1 ? KNOWN.length : i;
}

// Next job to do first: earliest service date, jobs without a date last.
function byServiceDate(a: Job, b: Job): number {
  if (a.service_date === b.service_date) return 0;
  if (a.service_date === null) return 1;
  if (b.service_date === null) return -1;
  return a.service_date < b.service_date ? -1 : 1;
}

export interface GroupedJobs {
  section: JobSection;
  jobs: Job[];
}

export function groupJobs(jobs: Job[], statusFilter: string | null = null): GroupedJobs[] {
  const shown = statusFilter ? jobs.filter((j) => j.status === statusFilter) : jobs;
  return [...JOB_SECTIONS, OTHER]
    .map((section) => ({
      section,
      jobs: shown
        .filter((j) => sectionFor(j.status) === section)
        .sort((a, b) => statusRank(a.status) - statusRank(b.status) || byServiceDate(a, b)),
    }))
    .filter((g) => g.jobs.length > 0);
}

export interface StatusCount {
  status: string;
  count: number;
}

// Chip data: only statuses that appear, in section order then status order; unknown ones last.
export function statusCounts(jobs: Job[]): StatusCount[] {
  const counts = new Map<string, number>();
  for (const j of jobs) counts.set(j.status, (counts.get(j.status) ?? 0) + 1);
  const unknown = [...counts.keys()].filter((s) => !KNOWN.includes(s)).sort();
  return [...KNOWN, ...unknown].filter((s) => counts.has(s)).map((status) => ({ status, count: counts.get(status)! }));
}
