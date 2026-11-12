import { http, HttpResponse } from "msw";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { deferred } from "@/test/deferred";
import { makeJob } from "@/test/fixtures";
import { API } from "@/test/handlers";
import { paypal } from "@/test/paypal-stub";
import { renderRoute } from "@/test/render";
import { find } from "@/test/requests";
import { server } from "@/test/server";
import {
  addressBox,
  cleanerRadio,
  cleanersHandler,
  dateBox,
  emailBox,
  fillValidForm,
  freezeToday,
  makeAvailability,
  nameBox,
  setDate,
  tierRadio,
} from "@/test/book";

vi.mock("@paypal/react-paypal-js", async () => (await import("@/test/paypal-stub")).paypalModule);

const ana = makeAvailability({ id: "c1", name: "Ana" });
const bo = makeAvailability({ id: "c2", name: "Bo" });
const FIX_FIELDS = "Please fix the highlighted fields before paying.";

beforeEach(() => {
  freezeToday();
  server.use(cleanersHandler([ana, bo]));
});

/** Renders /book with a fully valid form (Ana, 2026-11-20). */
async function ready(path = "/book") {
  const user = userEvent.setup();
  renderRoute(path);
  await fillValidForm(user);
  return user;
}

/** Calls the buttons' createOrder; resolves to the order id or the thrown error. */
async function createOrder(): Promise<{ orderId?: string; error?: Error }> {
  let out: { orderId?: string; error?: Error } = {};
  await act(async () => {
    try {
      out = { orderId: await paypal.props.createOrder() };
    } catch (e) {
      out = { error: e as Error };
    }
  });
  return out;
}

const click = async () => {
  const actions = { resolve: vi.fn(() => "resolved"), reject: vi.fn(() => "rejected") };
  await act(async () => {
    paypal.props.onClick({}, actions);
  });
  return actions;
};
const approve = (orderID = "o1") =>
  act(async () => {
    await paypal.props.onApprove({ orderID });
  });
const createJobs = () => find("POST", "/api/jobs");
const orders = () => find("POST", "/api/jobs/j1/paypal/order");
const alertText = () => screen.getByRole("alert").textContent;

describe("Book: makeOrder (through createOrder)", () => {
  it("throws on an invalid form and sends no createJob", async () => {
    renderRoute("/book");
    const { error } = await createOrder();
    expect(error?.message).toBe("Please fix the highlighted fields.");
    expect(createJobs()).toHaveLength(0);
    expect(find("POST", "/api/jobs/j1/paypal/order")).toHaveLength(0);
    expect(alertText()).toBe("Please fix the highlighted fields.");
  });

  it("sends trimmed details, with service type and amount from the tier", async () => {
    const user = userEvent.setup();
    renderRoute("/book?tier=deep");
    await user.type(nameBox(), "  Sam  ");
    await user.type(emailBox(), "  sam@example.com ");
    await user.type(addressBox(), " 1 Main St  ");
    setDate("2026-11-20");
    await user.click(await screen.findByRole("radio", { name: /^Ana/ }));
    const { orderId } = await createOrder();
    expect(orderId).toBe("o1");
    expect(createJobs()).toHaveLength(1);
    expect(createJobs()[0].body).toEqual({
      customer_name: "Sam",
      customer_email: "sam@example.com",
      address: "1 Main St",
      service_type: "deep",
      cleaner_id: "c1",
      service_date: "2026-11-20",
      amount: 20,
    });
  });

  it("reuses the job when called twice with identical details", async () => {
    await ready();
    await createOrder();
    await createOrder();
    expect(createJobs()).toHaveLength(1);
    expect(orders()).toHaveLength(2);
  });

  it("still reuses the job when only whitespace changes", async () => {
    const user = await ready();
    await createOrder();
    await user.type(nameBox(), " ");
    expect(nameBox()).toHaveValue("Sam ");
    await createOrder();
    expect(createJobs()).toHaveLength(1);
    expect(orders()).toHaveLength(2);
  });

  it.each([
    ["name", async (u: ReturnType<typeof userEvent.setup>) => u.type(nameBox(), "x")],
    ["email", async (u: ReturnType<typeof userEvent.setup>) => u.type(emailBox(), "m")],
    ["address", async (u: ReturnType<typeof userEvent.setup>) => u.type(addressBox(), "x")],
    ["tier", async (u: ReturnType<typeof userEvent.setup>) => u.click(tierRadio(/Deep Clean/))],
    ["cleaner", async (u: ReturnType<typeof userEvent.setup>) => u.click(cleanerRadio(/^Bo/))],
    [
      "date",
      async () => {
        setDate("2026-11-21");
        await screen.findByRole("radio", { name: /^Ana/ });
        await userEvent.setup().click(cleanerRadio(/^Ana/));
      },
    ],
  ])("sends a new createJob when the %s changes", async (_label, change) => {
    const user = await ready();
    await createOrder();
    await change(user);
    const { error } = await createOrder();
    expect(error).toBeUndefined();
    expect(createJobs()).toHaveLength(2);
  });

  it("retries only createOrder when createJob worked but createOrder failed", async () => {
    let calls = 0;
    server.use(
      http.post(`${API}/jobs/:id/paypal/order`, () =>
        ++calls === 1 ? HttpResponse.json({ detail: "PayPal is down" }, { status: 502 }) : HttpResponse.json({ order_id: "o2" }),
      ),
    );
    await ready();
    const first = await createOrder();
    expect(first.error?.message).toBe("PayPal is down");
    expect(alertText()).toBe("PayPal is down");
    const second = await createOrder();
    expect(second.orderId).toBe("o2");
    expect(createJobs()).toHaveLength(1);
    expect(orders()).toHaveLength(2);
  });

  it.each([409, 404])("on a %s, clears the cleaner, reloads the list and asks for a new choice", async (status) => {
    server.use(http.post(`${API}/jobs`, () => HttpResponse.json({ detail: "That cleaner was just booked." }, { status })));
    await ready();
    expect(find("GET", "/api/cleaners")).toHaveLength(1);
    const { error } = await createOrder();
    expect(error?.message).toBe("That cleaner was just booked. Please choose a cleaner again.");
    expect(alertText()).toMatch(/Please choose a cleaner again\.$/);
    await waitFor(() => expect(find("GET", "/api/cleaners")).toHaveLength(2));
    expect(await screen.findByRole("radio", { name: /^Ana/ })).not.toBeChecked();
    expect(screen.getByRole("complementary")).not.toHaveTextContent("· Ana");
    expect(document.activeElement).toBe(screen.getByText("Choose your cleaner"));
    expect(orders()).toHaveLength(0);
  });

  it("shows a 500 message as-is and keeps the cleaner selected", async () => {
    server.use(http.post(`${API}/jobs`, () => HttpResponse.json({ detail: "Database on fire" }, { status: 500 })));
    await ready();
    const { error } = await createOrder();
    expect(error?.message).toBe("Database on fire");
    expect(alertText()).toBe("Database on fire");
    expect(cleanerRadio(/^Ana/)).toBeChecked();
    expect(find("GET", "/api/cleaners")).toHaveLength(1);
  });
});

describe("Book: PayPal callbacks", () => {
  it("onClick on an invalid form rejects, shows every field error and the top alert", async () => {
    renderRoute("/book");
    const actions = await click();
    expect(actions.reject).toHaveBeenCalledOnce();
    expect(actions.resolve).not.toHaveBeenCalled();
    for (const m of ["Enter your name.", "Enter your email.", "Enter the address to clean.", "Pick a date."]) {
      expect(screen.getByText(m)).toBeInTheDocument();
    }
    expect(alertText()).toBe(FIX_FIELDS);
  });

  it("onClick on a valid form resolves and clears the error", async () => {
    await ready();
    await act(async () => paypal.props.onCancel());
    expect(alertText()).toMatch(/cancelled/);
    const actions = await click();
    expect(actions.resolve).toHaveBeenCalledOnce();
    expect(actions.reject).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("onApprove authorizes the job with the order id and lands on /booked/:id", async () => {
    await ready();
    await createOrder();
    await approve("order-9");
    expect(find("POST", "/api/jobs/j1/paypal/authorize")[0].body).toEqual({ order_id: "order-9" });
    await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/booked/j1"));
  });

  it("onApprove failure says nothing was charged and re-enables the form", async () => {
    server.use(http.post(`${API}/jobs/:id/paypal/authorize`, () => HttpResponse.json({ detail: "Card declined." }, { status: 402 })));
    await ready();
    await createOrder();
    await approve();
    expect(alertText()).toContain("Card declined.");
    expect(alertText()).toMatch(/you have not been charged\.$/);
    expect(screen.getByTestId("pathname")).toHaveTextContent("/book");
    for (const el of [nameBox(), emailBox(), addressBox(), dateBox(), tierRadio(/Basic/), cleanerRadio(/^Ana/)]) {
      expect(el).toBeEnabled();
    }
  });

  it("disables the fields, tiers and cleaners while onApprove is pending", async () => {
    const gate = deferred();
    server.use(
      http.post(`${API}/jobs/:id/paypal/authorize`, async () => {
        await gate.promise;
        return HttpResponse.json(makeJob());
      }),
    );
    await ready();
    await createOrder();
    let done!: Promise<void>;
    try {
      await act(async () => {
        done = paypal.props.onApprove({ orderID: "o1" });
      });
      for (const el of [nameBox(), emailBox(), addressBox(), dateBox(), tierRadio(/Basic/), tierRadio(/Deep/), cleanerRadio(/^Ana/), cleanerRadio(/^Bo/)]) {
        expect(el).toBeDisabled();
      }
    } finally {
      gate.release();
    }
    await act(async () => {
      await done;
    });
    await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent("/booked/j1"));
  });

  it("onCancel shows the cancelled message, replacing an existing error", async () => {
    renderRoute("/book");
    await click();
    expect(alertText()).toBe(FIX_FIELDS);
    await act(async () => paypal.props.onCancel());
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(alertText()).toBe("Payment was cancelled. You have not been charged.");
  });

  it("onError shows the PayPal message only when no error is showing", async () => {
    renderRoute("/book");
    await act(async () => paypal.props.onError(new Error("boom")));
    expect(alertText()).toBe("Something went wrong with PayPal. Please try again.");
    await act(async () => paypal.props.onCancel());
    await act(async () => paypal.props.onError(new Error("boom")));
    expect(alertText()).toBe("Payment was cancelled. You have not been charged.");
  });

  it("onError keeps an existing 409 message", async () => {
    server.use(http.post(`${API}/jobs`, () => HttpResponse.json({ detail: "Taken." }, { status: 409 })));
    await ready();
    await createOrder();
    await act(async () => paypal.props.onError(new Error("boom")));
    expect(alertText()).toBe("Taken. Please choose a cleaner again.");
  });
});

describe("Book: config", () => {
  it("shows the setup alert and no PayPal button when VITE_PAYPAL_CLIENT_ID is empty", async () => {
    vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "");
    vi.resetModules();
    const { default: FreshBook } = await import("./Book");
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <FreshBook />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Set VITE_PAYPAL_CLIENT_ID in web/.env to show the PayPal button.");
    expect(screen.queryByRole("button", { name: "PayPal" })).not.toBeInTheDocument();
  });
});
