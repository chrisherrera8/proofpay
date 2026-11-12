import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { resetRequests, startRecording } from "./requests";
import { server } from "./server";

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
  startRecording(server);
});
// jsdom has no matchMedia. Default to a narrow screen; tests can override window.matchMedia for the split view.
beforeEach(() => {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
});
beforeEach(resetRequests);
afterEach(() => {
  cleanup();
  server.resetHandlers();
  localStorage.clear();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
afterAll(() => server.close());
