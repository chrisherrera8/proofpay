import { http, HttpResponse } from "msw";
import { makeCleaner, makeJob } from "./fixtures";

// `.env` doesn't set VITE_API_URL, so api.ts falls back to this base.
export const API = "http://localhost:8000/api";

// Happy-path defaults. Tests override single routes with `server.use(...)`.
export const handlers = [
  http.post(`${API}/jobs`, () => HttpResponse.json(makeJob())),
  http.get(`${API}/jobs`, () => HttpResponse.json([])),
  http.get(`${API}/jobs/:id`, ({ params }) => HttpResponse.json(makeJob({ id: String(params.id) }))),
  http.post(`${API}/jobs/:id/paypal/order`, () => HttpResponse.json({ order_id: "o1" })),
  http.post(`${API}/jobs/:id/paypal/authorize`, ({ params }) =>
    HttpResponse.json(makeJob({ id: String(params.id) })),
  ),
  http.post(`${API}/jobs/:id/submit`, ({ params }) =>
    HttpResponse.json(makeJob({ id: String(params.id), status: "SUBMITTED" })),
  ),
  http.post(`${API}/jobs/:id/verify`, ({ params }) =>
    HttpResponse.json(makeJob({ id: String(params.id), status: "VERIFIED" })),
  ),
  http.post(`${API}/jobs/:id/settle`, ({ params }) => HttpResponse.json(makeJob({ id: String(params.id) }))),
  http.get(`${API}/jobs/:id/photos`, () => HttpResponse.json([])),
  http.post(`${API}/jobs/:id/photos`, () => HttpResponse.json({ id: 1, kind: "before" })),
  http.delete(`${API}/jobs/:id/photos/:photoId`, () => new HttpResponse(null, { status: 204 })),
  http.post(`${API}/cleaners`, () => HttpResponse.json(makeCleaner())),
  http.get(`${API}/cleaners`, () => HttpResponse.json([{ ...makeCleaner(), available: true }])),
  http.get(`${API}/cleaners/:id`, ({ params }) => HttpResponse.json(makeCleaner({ id: String(params.id) }))),
];
