import { http, HttpResponse } from "msw";
import type { Job, Photo } from "@/api";
import { API } from "./handlers";
import { server } from "./server";

export const makePhoto = (id: number, kind: Photo["kind"] = "before"): Photo => ({ id, kind });

/**
 * Serves `getJob` and `listPhotos` from a mutable state object, so a test (or a handler it adds)
 * can change what the next refresh returns.
 */
export function serveJob(job: Job, photos: Photo[] = []) {
  const state = { job, photos };
  server.use(
    http.get(`${API}/jobs/:id`, () => HttpResponse.json(state.job)),
    http.get(`${API}/jobs/:id/photos`, () => HttpResponse.json(state.photos)),
  );
  return state;
}
