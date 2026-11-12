import { StrictMode } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AppRoutes } from "@/routes";

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

export function renderRoute(path: string, { state }: { state?: unknown } = {}) {
  return render(
    <StrictMode>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={[{ pathname: path.split("?")[0], search: path.split("?")[1] ? `?${path.split("?")[1]}` : "", state }]}>
        <AppRoutes />
        <LocationProbe />
      </MemoryRouter>
    </StrictMode>,
  );
}
