import { StrictMode } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import Book from "@/pages/Book";
import Booked from "@/pages/Booked";
import CleanerJob from "@/pages/CleanerJob";
import CleanerJobs from "@/pages/CleanerJobs";
import CleanerSignup from "@/pages/CleanerSignup";
import Home from "@/pages/Home";

/** Prints the current location so tests can assert on redirects and navigation state. */
export function LocationProbe() {
  const { pathname, search, state } = useLocation();
  return (
    <>
      <output data-testid="pathname">{pathname}</output>
      <output data-testid="search">{search}</output>
      <output data-testid="state">{JSON.stringify(state)}</output>
    </>
  );
}

// Same paths as main.tsx. Phase 7 moves this tree into a shared AppRoutes.
export function renderRoute(path: string, { state }: { state?: unknown } = {}) {
  return render(
    <StrictMode>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={[{ pathname: path.split("?")[0], search: path.split("?")[1] ? `?${path.split("?")[1]}` : "", state }]}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/book" element={<Book />} />
          <Route path="/booked/:jobId" element={<Booked />} />
          <Route path="/cleaner" element={<CleanerJobs />} />
          <Route path="/cleaner/signup" element={<CleanerSignup />} />
          <Route path="/cleaner/:jobId" element={<CleanerJob />} />
          <Route path="*" element={<Home />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </StrictMode>,
  );
}
