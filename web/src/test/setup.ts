import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { resetRequests, startRecording } from "./requests";
import { server } from "./server";

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  startRecording(server);
});
beforeEach(resetRequests);
afterEach(() => {
  cleanup();
  server.resetHandlers();
  localStorage.clear();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});
afterAll(() => server.close());
