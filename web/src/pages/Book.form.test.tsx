import { setCleanerId } from "@/lib/cleaner-session";
import { http, HttpResponse } from "msw";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { deferred } from "@/test/deferred";
import { API } from "@/test/handlers";
import { renderRoute } from "@/test/render";
import { find } from "@/test/requests";
import { server } from "@/test/server";
import { paypal } from "@/test/paypal-stub";
import {
  addressBox,
  cleanersHandler,
  cleanerRadio,
  dateBox,
  emailBox,
  fillDetails,
  freezeToday,
  makeAvailability,
  nameBox,
  setDate,
  tierRadio,
} from "@/test/book";

vi.mock("@paypal/react-paypal-js", async () => (await import("@/test/paypal-stub")).paypalModule);

const ana = makeAvailability({ id: "c1", name: "Ana", is_seed: true });
const bo = makeAvailability({ id: "c2", name: "Bo" });

beforeEach(() => {
  setCleanerId("c2"); // Bo is the signed-in cleaner
  freezeToday();
  server.use(cleanersHandler([ana, bo]));
});

describe("Book: service tier", () => {
  it.each([
    ["no ?tier=", "/book"],
    ["an unknown ?tier=", "/book?tier=bogus"],
  ])("selects Basic at ten dollars with %s", (_label, path) => {
    renderRoute(path);
    expect(tierRadio(/Basic Clean/)).toBeChecked();
    expect(tierRadio(/Deep Clean/)).not.toBeChecked();
    expect(screen.getAllByText("$10.00")).toHaveLength(2);
  });

  it("sets ?tier=deep and shows $20.00 in the summary twice when Deep Clean is clicked", async () => {
    const user = userEvent.setup();
    renderRoute("/book");
    await user.click(tierRadio(/Deep Clean/));
    expect(tierRadio(/Deep Clean/)).toBeChecked();
    expect(screen.getByTestId("search")).toHaveTextContent("?tier=deep");
    expect(screen.getAllByText("$20.00")).toHaveLength(2);
    expect(screen.queryByText("$10.00")).not.toBeInTheDocument();
  });
});

describe("Book: validation and error timing", () => {
  it.each([
    ["name", () => nameBox(), "Enter your name."],
    ["email", () => emailBox(), "Enter your email."],
    ["address", () => addressBox(), "Enter the address to clean."],
    ["date", () => dateBox(), "Pick a date."],
  ])("shows the %s error only after that field is blurred", async (_label, box, message) => {
    const user = userEvent.setup();
    renderRoute("/book");
    await user.click(box());
    expect(screen.queryByText(message)).not.toBeInTheDocument();
    await user.tab();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(box()).toHaveAccessibleDescription(expect.stringContaining(message));
    // Only the blurred field complains.
    expect(screen.getAllByText(/^(Enter |Pick a date\.)/)).toHaveLength(1);
  });

  it.each([
    ["a bad email", "Sam", "a@b", "1 Main St", "Enter a valid email, like name@example.com."],
    ["a whitespace-only name", "   ", "sam@example.com", "1 Main St", "Enter your name."],
    ["a whitespace-only address", "Sam", "sam@example.com", "   ", "Enter the address to clean."],
  ])("rejects %s", async (_label, name, email, address, message) => {
    const user = userEvent.setup();
    renderRoute("/book");
    await fillDetails(user, { name, email, address });
    await user.tab();
    expect(screen.getByText(message)).toBeInTheDocument();
  });

  it("rejects a past date and hides the cleaner picker", () => {
    renderRoute("/book");
    setDate("2026-11-09");
    expect(screen.getByText("Pick a date that isn't in the past.")).toBeInTheDocument();
    expect(screen.queryByText("Choose your cleaner")).not.toBeInTheDocument();
    expect(find("GET", "/api/cleaners")).toHaveLength(0);
  });

  it.each([
    ["today", "2026-11-10"],
    ["tomorrow", "2026-11-11"],
  ])("accepts %s", async (_label, date) => {
    renderRoute("/book");
    setDate(date);
    expect(screen.queryByText("Pick a date that isn't in the past.")).not.toBeInTheDocument();
    expect(await screen.findByText("Choose your cleaner")).toBeInTheDocument();
  });

  it.each([
    ["name", () => nameBox()],
    ["email", () => emailBox()],
    ["address", () => addressBox()],
  ])("clears the top-level alert when the %s changes", async (_label, box) => {
    const user = userEvent.setup();
    renderRoute("/book");
    await act(async () => {
      paypal.props.onClick({}, { resolve: vi.fn(), reject: vi.fn() });
    });
    expect(await screen.findByText("Please fix the highlighted fields before paying.")).toBeInTheDocument();
    await user.type(box(), "x");
    expect(screen.queryByText("Please fix the highlighted fields before paying.")).not.toBeInTheDocument();
  });

  it("clears the top-level alert when the date changes", async () => {
    renderRoute("/book");
    await act(async () => {
      paypal.props.onClick({}, { resolve: vi.fn(), reject: vi.fn() });
    });
    expect(await screen.findByText("Please fix the highlighted fields before paying.")).toBeInTheDocument();
    setDate("2026-11-20");
    expect(screen.queryByText("Please fix the highlighted fields before paying.")).not.toBeInTheDocument();
  });
});

describe("Book: cleaner picker", () => {
  it("stays hidden until a valid date is set, then shows loading and the list", async () => {
    const gate = deferred();
    server.use(
      http.get(`${API}/cleaners`, async () => {
        await gate.promise;
        return HttpResponse.json([ana, bo]);
      }),
    );
    renderRoute("/book");
    expect(screen.queryByText("Choose your cleaner")).not.toBeInTheDocument();
    try {
      setDate("2026-11-20");
      expect(await screen.findByRole("status", { name: "Loading cleaners" })).toBeInTheDocument();
    } finally {
      gate.release();
    }
    expect(await cleanerRadioFind(/^Ana/)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading cleaners" })).not.toBeInTheDocument();
    expect(find("GET", "/api/cleaners")[0].url.searchParams.get("date")).toBe("2026-11-20");
  });

  it("disables unavailable cleaners as booked and shows available ones as free", async () => {
    server.use(cleanersHandler([ana, makeAvailability({ id: "c2", name: "Bo", available: false })]));
    renderRoute("/book");
    setDate("2026-11-20");
    const free = await cleanerRadioFind(/^Ana/);
    expect(free).toHaveTextContent("Free");
    expect(free).toBeEnabled();
    const booked = cleanerRadio(/^Bo/);
    expect(booked).toHaveTextContent("Booked on Fri, Nov 20");
    expect(booked).toBeDisabled();
    expect(screen.queryByText("Everyone is booked that day. Try another date.")).not.toBeInTheDocument();
  });

  it("says everyone is booked when no cleaner is available", async () => {
    server.use(cleanersHandler([makeAvailability({ available: false })]));
    renderRoute("/book");
    setDate("2026-11-20");
    expect(await screen.findByText("Everyone is booked that day. Try another date.")).toBeInTheDocument();
  });

  it("shows the error inside the fieldset when listCleaners fails", async () => {
    server.use(http.get(`${API}/cleaners`, () => HttpResponse.json({ detail: "Cleaners are down" }, { status: 500 })));
    renderRoute("/book");
    setDate("2026-11-20");
    const group = await screen.findByRole("group", { name: "Choose your cleaner" });
    expect(await within(group).findByRole("alert")).toHaveTextContent("Cleaners are down");
    expect(within(group).queryByRole("status")).not.toBeInTheDocument();
  });

  it("adds the picked cleaner to the summary's Day row", async () => {
    const user = userEvent.setup();
    renderRoute("/book");
    setDate("2026-11-20");
    const summary = screen.getByRole("complementary");
    expect(within(summary).getByText("Fri, Nov 20")).toBeInTheDocument();
    await user.click(await cleanerRadioFind(/^Ana/));
    expect(within(summary).getByText("Fri, Nov 20 · Ana")).toBeInTheDocument();
  });

  it("drops the selection when the picked cleaner is booked on the new date, and keeps it when free", async () => {
    server.use(
      cleanersHandler([ana, bo], {
        "2026-11-21": [makeAvailability({ id: "c1", name: "Ana", is_seed: true, available: false }), bo],
        "2026-11-22": [ana, bo],
      }),
    );
    const user = userEvent.setup();
    renderRoute("/book");
    setDate("2026-11-20");
    await user.click(await cleanerRadioFind(/^Ana/));
    expect(cleanerRadio(/^Ana/)).toBeChecked();

    setDate("2026-11-21");
    await waitFor(() => expect(cleanerRadio(/^Ana/)).toBeDisabled());
    expect(cleanerRadio(/^Ana/)).not.toBeChecked();
    expect(screen.getByRole("complementary")).not.toHaveTextContent("· Ana");

    await user.click(cleanerRadio(/^Bo/));
    setDate("2026-11-22");
    await waitFor(() => expect(cleanerRadio(/^Bo/)).toBeEnabled());
    expect(cleanerRadio(/^Bo/)).toBeChecked();
    expect(screen.getByRole("complementary")).toHaveTextContent("· Bo");
  });

  it("keeps the newest date's list when an older response arrives last", async () => {
    const first = deferred();
    const staleSent = new Promise<void>((resolve) => {
      const onMocked = ({ request }: { request: Request }) => {
        if (new URL(request.url).searchParams.get("date") === "2026-11-20") {
          server.events.removeListener("response:mocked", onMocked);
          resolve();
        }
      };
      server.events.on("response:mocked", onMocked);
    });
    server.use(
      http.get(`${API}/cleaners`, async ({ request }) => {
        const date = new URL(request.url).searchParams.get("date");
        if (date === "2026-11-20") {
          await first.promise;
          return HttpResponse.json([makeAvailability({ id: "old", name: "Old" })]);
        }
        return HttpResponse.json([makeAvailability({ id: "new", name: "New", is_seed: true })]);
      }),
    );
    renderRoute("/book");
    try {
      setDate("2026-11-20");
      await waitFor(() => expect(find("GET", "/api/cleaners")).toHaveLength(1));
      setDate("2026-11-21");
      expect(await cleanerRadioFind(/^New/)).toBeInTheDocument();
    } finally {
      first.release();
    }
    // Wait for the server to actually send the stale response, then let the
    // client consume it before checking it was ignored.
    await staleSent;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(find("GET", "/api/cleaners")).toHaveLength(2);
    expect(screen.getByRole("radio", { name: /^New/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /^Old/ })).not.toBeInTheDocument();
  });
});

const cleanerRadioFind = (name: RegExp) => screen.findByRole("radio", { name });

describe("Book: who is listed", () => {
  it("hides other cleaners and offers registration when not signed in as one", async () => {
    localStorage.clear();
    renderRoute("/book");
    setDate("2026-11-20");
    expect(await cleanerRadioFind(/^Ana/)).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /^Bo/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Register your cleaner" })).toHaveAttribute("href", "/cleaner/signup");
  });

  it("lists the signed-in cleaner and drops the registration prompt", async () => {
    renderRoute("/book");
    setDate("2026-11-20");
    expect(await cleanerRadioFind(/^Bo/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Register your cleaner" })).not.toBeInTheDocument();
  });
});
