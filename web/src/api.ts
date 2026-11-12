const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface Job {
  id: string;
  status: string;
  customer_name: string;
  customer_email: string;
  address: string;
  service_type: string;
  scheduled_at: string;
  service_date: string | null; // YYYY-MM-DD
  strict_check: boolean; // unseen checklist items fail the photo check
  cleaner_id: string | null;
  cleaner_name: string | null; // null once the cleaner's data was deleted
  amount: string;
  currency: string;
  checklist_items: { id: number; label: string; required: boolean; position: number }[];
  verification: Verification | null;
  decision: Decision | null;
  payout: Payout | null;
}

export interface Payout {
  amount: string;
  status: string; // PENDING, SUCCESS or FAILED
}

export interface Decision {
  outcome: "auto_release" | "needs_approval" | "reject";
  reasons: string[];
}

export interface VerificationItem {
  item: string;
  visible: boolean;
  pass: boolean;
  confidence: number;
  note: string;
}

export interface Verification {
  id: number;
  score: string | null;
  model: string;
  results: { overall_pass: boolean; items: VerificationItem[] };
}

export interface Photo {
  id: number;
  kind: "before" | "after";
}

export interface Cleaner {
  id: string;
  name: string;
  is_seed: boolean;
  created_at: string;
}

export interface CleanerAvailability extends Cleaner {
  available: boolean;
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
  }
}

// FastAPI sends 422 details as a list of {loc, msg}; turn that into one readable line.
function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${String(d.loc?.at(-1) ?? "field")}: ${String(d.msg ?? "invalid").replace(/^Value error, /, "")}`)
      .join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit, contentType = "application/json"): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers: { "Content-Type": contentType } });
  } catch {
    throw new ApiError("Can't reach the booking server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* no JSON body */
    }
    throw new ApiError(describe(detail, `Something went wrong (${res.status}). Please try again.`), res.status);
  }
  if (res.status === 204) return undefined as T;
  try {
    return await res.json();
  } catch {
    throw new ApiError("The server sent an unexpected response. Please try again.", res.status);
  }
}

export const createJob = (body: {
  customer_name: string;
  customer_email: string;
  address: string;
  service_type: string;
  cleaner_id: string;
  service_date: string; // YYYY-MM-DD
  amount: number;
  strict_check?: boolean;
}) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(body) });

export const createOrder = (jobId: string) =>
  request<{ order_id: string }>(`/api/jobs/${jobId}/paypal/order`, { method: "POST" });

export const authorize = (jobId: string, orderId: string) =>
  request<Job>(`/api/jobs/${jobId}/paypal/authorize`, {
    method: "POST",
    body: JSON.stringify({ order_id: orderId }),
  });

export const getJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}`);

export const listJobs = (cleanerId: string, opts: { status?: string; limit?: number } = {}) => {
  const params = new URLSearchParams({ cleaner_id: cleanerId });
  if (opts.status !== undefined) params.set("status", opts.status);
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  return request<Job[]>(`/api/jobs?${params}`);
};

// `known_id` is the cleaner id this browser already holds; `confirmed` says the person confirmed an existing
// account with this email is theirs. Without either, the API answers 409 when the email is already taken.
export const signUp = (body: { name: string; paypal_email: string; known_id?: string | null; confirmed?: boolean }) =>
  request<Cleaner>("/api/cleaners", { method: "POST", body: JSON.stringify(body) });

export const listCleaners = (date: string) =>
  request<CleanerAvailability[]>(`/api/cleaners?date=${encodeURIComponent(date)}`);

export const getCleaner = (id: string) => request<Cleaner>(`/api/cleaners/${encodeURIComponent(id)}`);

export const listPhotos = (jobId: string) => request<Photo[]>(`/api/jobs/${jobId}/photos`);

export const photoUrl = (jobId: string, photoId: number) => `${BASE}/api/jobs/${jobId}/photos/${photoId}`;

export const uploadPhoto = (jobId: string, kind: Photo["kind"], blob: Blob) =>
  request<Photo>(`/api/jobs/${jobId}/photos?kind=${kind}`, { method: "POST", body: blob }, blob.type);

export const deletePhoto = (jobId: string, photoId: number) =>
  request<void>(`/api/jobs/${jobId}/photos/${photoId}`, { method: "DELETE" });

// The vision check takes ~5-10s, and a cold free-tier server adds up to a minute.
export const submitJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}/submit`, { method: "POST" });

export const verifyJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}/verify`, { method: "POST" });

// Does the next missing payment step (capture, payout, or checking whether the payout landed).
export const settleJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}/settle`, { method: "POST" });
