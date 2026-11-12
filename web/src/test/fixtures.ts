import type { Cleaner, Job, Verification } from "@/api";

export const makeVerification = (overrides: Partial<Verification> = {}): Verification => ({
  id: 1,
  score: "0.92",
  model: "test-model",
  results: { overall_pass: true, items: [] },
  ...overrides,
});

export const makeCleaner = (overrides: Partial<Cleaner> = {}): Cleaner => ({
  id: "c1",
  name: "Ana",
  is_seed: false,
  created_at: "2026-11-10T12:00:00Z",
  ...overrides,
});

export const makeJob = (overrides: Partial<Job> = {}): Job => ({
  id: "j1",
  status: "AUTHORIZED",
  customer_name: "Sam",
  customer_email: "sam@example.com",
  address: "1 Main St",
  service_type: "basic",
  scheduled_at: "2026-11-20T09:00:00Z",
  service_date: "2026-11-20",
  cleaner_id: "c1",
  cleaner_name: "Ana",
  amount: "10.00",
  currency: "USD",
  strict_check: false,
  checklist_items: [{ id: 1, label: "Wipe the counters", required: true, position: 1 }],
  verification: null,
  decision: null,
  payout: null,
  ...overrides,
});
