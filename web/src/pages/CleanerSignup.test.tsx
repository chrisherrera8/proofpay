import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { API } from "@/test/handlers";
import { makeCleaner } from "@/test/fixtures";
import { find } from "@/test/requests";
import { renderRoute } from "@/test/render";
import { server } from "@/test/server";

const nameBox = () => screen.getByRole("textbox", { name: /your name/i });
const emailBox = () => screen.getByRole("textbox", { name: /paypal email/i });
const signUpButton = () => screen.getByRole("button", { name: "Sign up" });

async function fillValid(user: ReturnType<typeof userEvent.setup>, name = "  Ana  ", email = "  ana@example.com  ") {
  await user.type(nameBox(), name);
  await user.type(emailBox(), email);
}

describe("CleanerSignup", () => {
  describe("validation", () => {
    it("shows both errors on an empty submit and sends nothing", async () => {
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await user.click(signUpButton());
      expect(screen.getByText("Enter your name.")).toBeInTheDocument();
      expect(screen.getByText("Enter your PayPal email.")).toBeInTheDocument();
      expect(find("POST", "/api/cleaners")).toHaveLength(0);
    });

    it("shows a field's error only after it is blurred", async () => {
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await user.type(nameBox(), "A");
      await user.clear(nameBox());
      expect(screen.queryByText("Enter your name.")).not.toBeInTheDocument();
      await user.tab();
      expect(screen.getByText("Enter your name.")).toBeInTheDocument();
      expect(screen.queryByText("Enter your PayPal email.")).not.toBeInTheDocument();
    });

    it.each([
      ["whitespace-only name", "   ", "ana@example.com", "Enter your name."],
      ["bad email", "Ana", "a@b", "Enter a valid email, like name@example.com."],
    ])("rejects a %s", async (_label, name, email, message) => {
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await user.type(nameBox(), name);
      await user.type(emailBox(), email);
      await user.click(signUpButton());
      expect(screen.getByText(message)).toBeInTheDocument();
      expect(find("POST", "/api/cleaners")).toHaveLength(0);
    });
  });

  describe("submit", () => {
    it("sends trimmed values, stores the id and lands on /cleaner", async () => {
      server.use(http.post(`${API}/cleaners`, () => HttpResponse.json(makeCleaner({ id: "new-id" }))));
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await fillValid(user);
      await user.click(signUpButton());
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/cleaner$/));
      expect(find("POST", "/api/cleaners")[0].body).toEqual({ name: "Ana", paypal_email: "ana@example.com" });
      expect(localStorage.getItem("proofpay.cleanerId")).toBe("new-id");
    });

    it("shows a pending state and disables the inputs while the request is open", async () => {
      let release!: () => void;
      const gate = new Promise<void>((r) => (release = r));
      server.use(
        http.post(`${API}/cleaners`, async () => {
          await gate;
          return HttpResponse.json(makeCleaner());
        }),
      );
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await fillValid(user);
      await user.click(signUpButton());
      const busy = await screen.findByRole("button", { name: "Signing up" });
      expect(busy).toBeDisabled();
      expect(nameBox()).toBeDisabled();
      expect(emailBox()).toBeDisabled();
      release();
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/cleaner$/));
    });

    it("shows a 422 as one formatted alert and re-enables the form", async () => {
      server.use(
        http.post(`${API}/cleaners`, () =>
          HttpResponse.json(
            { detail: [{ loc: ["body", "paypal_email"], msg: "Value error, not a valid email" }] },
            { status: 422 },
          ),
        ),
      );
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await fillValid(user);
      await user.click(signUpButton());
      const alert = await screen.findByRole("alert");
      expect(screen.getAllByRole("alert")).toHaveLength(1);
      expect(alert).toHaveTextContent("paypal_email: not a valid email");
      expect(signUpButton()).toBeEnabled();
      expect(nameBox()).toBeEnabled();
      expect(emailBox()).toBeEnabled();
      expect(screen.getByTestId("pathname")).toHaveTextContent("/cleaner/signup");
      expect(localStorage.getItem("proofpay.cleanerId")).toBeNull();
    });

    it("clears the alert when the user types again", async () => {
      server.use(http.post(`${API}/cleaners`, () => HttpResponse.json({ detail: "Nope" }, { status: 400 })));
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await fillValid(user);
      await user.click(signUpButton());
      expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
      await user.type(nameBox(), "x");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("banner and demo link", () => {
    it("shows the expired banner only when navigation state says so", () => {
      const { unmount } = renderRoute("/cleaner/signup", { state: { expired: true } });
      expect(screen.getByText(/that cleaner account has expired/i)).toBeInTheDocument();
      unmount();
      renderRoute("/cleaner/signup");
      expect(screen.queryByText(/that cleaner account has expired/i)).not.toBeInTheDocument();
    });

    it("offers the seed cleaner, and clicking it stores the id and goes to /cleaner", async () => {
      server.use(
        http.get(`${API}/cleaners`, () =>
          HttpResponse.json([
            { ...makeCleaner({ id: "c2", name: "Bo" }), available: true },
            { ...makeCleaner({ id: "seed1", name: "Demo", is_seed: true }), available: true },
          ]),
        ),
      );
      const user = userEvent.setup();
      renderRoute("/cleaner/signup");
      await user.click(await screen.findByRole("button", { name: "Continue as Demo" }));
      expect(localStorage.getItem("proofpay.cleanerId")).toBe("seed1");
      await waitFor(() => expect(screen.getByTestId("pathname")).toHaveTextContent(/^\/cleaner$/));
    });

    it("shows no demo link and no error when there is no seed cleaner", async () => {
      renderRoute("/cleaner/signup");
      await waitFor(() => expect(find("GET", "/api/cleaners")).toHaveLength(2)); // StrictMode runs the effect twice
      expect(screen.queryByRole("button", { name: /continue as/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("shows no demo link and no error when listCleaners fails", async () => {
      server.use(http.get(`${API}/cleaners`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
      renderRoute("/cleaner/signup");
      await waitFor(() => expect(find("GET", "/api/cleaners")).toHaveLength(2));
      expect(screen.queryByRole("button", { name: /continue as/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });
});
