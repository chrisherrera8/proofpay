import { http, HttpResponse } from "msw";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { CleanerAvailability } from "@/api";
import { API } from "./handlers";
import { makeCleaner } from "./fixtures";

/** Book tests run on 2026-11-10 (a Tuesday), so 2026-11-20 is "Fri, Nov 20". Fakes only Date: faking timers stalls userEvent. */
export const TODAY = "2026-11-10";
export const freezeToday = () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 10, 10, 12, 0));
};

export const makeAvailability = (overrides: Partial<CleanerAvailability> = {}): CleanerAvailability => ({
  ...makeCleaner(),
  available: true,
  ...overrides,
});

/** `GET /cleaners?date=…` handler: `byDate` maps a date to its list, any other date gets `fallback`. */
export const cleanersHandler = (
  fallback: CleanerAvailability[],
  byDate: Record<string, CleanerAvailability[]> = {},
) =>
  http.get(`${API}/cleaners`, ({ request }) =>
    HttpResponse.json(byDate[new URL(request.url).searchParams.get("date") ?? ""] ?? fallback),
  );

export const nameBox = () => screen.getByRole("textbox", { name: "Full name" });
export const emailBox = () => screen.getByRole("textbox", { name: "Email" });
export const addressBox = () => screen.getByRole("textbox", { name: "Address" });
export const dateBox = () => screen.getByLabelText("Date");
export const tierRadio = (name: RegExp) => screen.getByRole("radio", { name });
export const cleanerRadio = (name: RegExp) => screen.getByRole("radio", { name });

/** Sets the date input directly: typing into `type="date"` is unreliable in jsdom. */
export const setDate = (value: string) => {
  fireEvent.change(dateBox(), { target: { value } });
  fireEvent.blur(dateBox());
};

type User = ReturnType<typeof userEvent.setup>;

export async function fillDetails(user: User, { name = "Sam", email = "sam@example.com", address = "1 Main St" } = {}) {
  await user.type(nameBox(), name);
  await user.type(emailBox(), email);
  await user.type(addressBox(), address);
}

/** Fills the whole form and picks the cleaner named in `cleanerName` (default "Ana") on 2026-11-20. */
export async function fillValidForm(user: User, cleanerName = /^Ana/) {
  await fillDetails(user);
  setDate("2026-11-20");
  await user.click(await screen.findByRole("radio", { name: cleanerName }));
}
