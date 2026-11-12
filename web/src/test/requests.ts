import type { SetupServer } from "msw/node";

export interface RecordedRequest {
  method: string;
  url: URL;
  headers: Headers;
  /** Parsed JSON when the body is JSON, the raw text otherwise, null when empty. */
  body: unknown;
}

/** Every request MSW saw during the current test, in order. Reset before each test. */
export const requests: RecordedRequest[] = [];

export const resetRequests = () => {
  requests.length = 0;
};

/** Requests matching a method and a path (without the host), e.g. `find("POST", "/api/cleaners")`. */
export const find = (method: string, pathname: string) =>
  requests.filter((r) => r.method === method && r.url.pathname === pathname);

export function startRecording(server: SetupServer) {
  server.events.on("request:start", async ({ request }) => {
    const text = await request.clone().text();
    let body: unknown = text || null;
    if (text && request.headers.get("content-type")?.includes("json")) {
      try {
        body = JSON.parse(text);
      } catch {
        /* keep the raw text */
      }
    }
    requests.push({ method: request.method, url: new URL(request.url), headers: request.headers, body });
  });
}
