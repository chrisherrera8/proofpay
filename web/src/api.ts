const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface Job {
  id: string;
  status: string;
  customer_name: string;
  customer_email: string;
  address: string;
  service_type: string;
  scheduled_at: string;
  amount: string;
  currency: string;
  checklist_items: { id: number; label: string; required: boolean; position: number }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const createJob = (body: {
  customer_name: string;
  customer_email: string;
  address: string;
  service_type: string;
  scheduled_at: string;
  amount: number;
}) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(body) });

export const createOrder = (jobId: string) =>
  request<{ order_id: string }>(`/api/jobs/${jobId}/paypal/order`, { method: "POST" });

export const authorize = (jobId: string, orderId: string) =>
  request<Job>(`/api/jobs/${jobId}/paypal/authorize`, {
    method: "POST",
    body: JSON.stringify({ order_id: orderId }),
  });

export const getJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}`);
