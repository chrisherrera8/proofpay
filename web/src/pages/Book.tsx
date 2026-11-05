import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PayPalButtons, PayPalScriptProvider } from "@paypal/react-paypal-js";
import { authorize, createJob, createOrder } from "../api";
import { TIERS, tierById } from "../tiers";

const CLIENT_ID = import.meta.env.VITE_PAYPAL_CLIENT_ID as string | undefined;

type Form = { name: string; email: string; address: string; when: string };
type Errors = Partial<Record<keyof Form, string>>;

// Matches the API's limits (JobCreate in app/schemas.py).
const MAX = { name: 200, email: 320, address: 500 };

function validate(f: Form): Errors {
  const e: Errors = {};
  if (!f.name.trim()) e.name = "Enter your name.";
  if (!f.email.trim()) e.email = "Enter your email.";
  else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim())) e.email = "Enter a valid email, like name@example.com.";
  if (!f.address.trim()) e.address = "Enter the address to clean.";
  if (!f.when) e.when = "Pick a date and time.";
  else if (new Date(f.when).getTime() <= Date.now()) e.when = "Pick a time in the future.";
  return e;
}

// datetime-local wants "YYYY-MM-DDTHH:mm" in local time.
function nowLocal(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

export default function Book() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const tier = tierById(params.get("tier")) ?? TIERS[0];
  const [form, setForm] = useState<Form>({ name: "", email: "", address: "", when: "" });
  const [touched, setTouched] = useState<Partial<Record<keyof Form, boolean>>>({});
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // PayPal buttons keep the callbacks from first render, so read the latest values via refs.
  const formRef = useRef(form);
  formRef.current = form;
  const tierRef = useRef(tier);
  tierRef.current = tier;
  // The job created for the current details. A new one is made if the details or tier change.
  const jobRef = useRef<{ id: string; key: string } | null>(null);

  const errors = validate(form);
  const hasErrors = Object.keys(errors).length > 0;
  const shown = (k: keyof Form) => (showAll || touched[k] ? errors[k] : undefined);

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [k]: e.target.value });
    setError(null);
  };
  const blur = (k: keyof Form) => () => setTouched({ ...touched, [k]: true });

  async function makeOrder(): Promise<string> {
    const f = formRef.current;
    const t = tierRef.current;
    // Re-validate: the form can change between the click check and this call.
    if (Object.keys(validate(f)).length) throw new Error("Please fix the highlighted fields.");
    const key = JSON.stringify([t.id, f.name.trim(), f.email.trim(), f.address.trim(), f.when]);
    // Reuse the job on a retry with identical details; the order endpoint is idempotent per job.
    if (!jobRef.current || jobRef.current.key !== key) {
      const job = await createJob({
        customer_name: f.name.trim(),
        customer_email: f.email.trim(),
        address: f.address.trim(),
        service_type: t.id,
        scheduled_at: new Date(f.when).toISOString(),
        amount: t.price,
      });
      jobRef.current = { id: job.id, key };
    }
    return (await createOrder(jobRef.current.id)).order_id;
  }

  const field = (k: keyof Form, label: string, props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <label>
      {label}
      <input
        {...props}
        value={form[k]}
        onChange={set(k)}
        onBlur={blur(k)}
        aria-invalid={!!shown(k)}
        aria-describedby={shown(k) ? `${k}-err` : undefined}
        disabled={busy}
      />
      {shown(k) && <span id={`${k}-err`} className="field-error">{shown(k)}</span>}
    </label>
  );

  return (
    <section className="section narrow">
      <h2>Book a clean</h2>
      <div className="tier-pick">
        {TIERS.map((t) => (
          <button
            key={t.id}
            type="button"
            disabled={busy}
            className={`pick${t.id === tier.id ? " active" : ""}`}
            onClick={() => setParams({ tier: t.id })}
          >
            {t.name} · ${t.price}
          </button>
        ))}
      </div>

      <form className="form" noValidate onSubmit={(e) => e.preventDefault()}>
        {field("name", "Full name", { autoComplete: "name", maxLength: MAX.name })}
        {field("email", "Email", { type: "email", autoComplete: "email", maxLength: MAX.email })}
        {field("address", "Address", { autoComplete: "street-address", maxLength: MAX.address })}
        {field("when", "Date and time", { type: "datetime-local", min: nowLocal() })}
      </form>

      <p className="total">Total today: <strong>${tier.price}.00</strong> <span className="muted">(authorized now, charged after the job is verified)</span></p>
      {error && <p className="error" role="alert">{error}</p>}

      {CLIENT_ID ? (
        <PayPalScriptProvider options={{ clientId: CLIENT_ID, intent: "authorize", currency: "USD" }}>
          <PayPalButtons
            style={{ layout: "vertical" }}
            disabled={busy}
            onClick={(_, actions) => {
              if (hasErrors) {
                setShowAll(true);
                setError("Please fix the highlighted fields before paying.");
                return actions.reject();
              }
              setError(null);
              return actions.resolve();
            }}
            createOrder={async () => {
              try {
                return await makeOrder();
              } catch (e) {
                setError((e as Error).message);
                throw e; // tells PayPal not to open the popup
              }
            }}
            onApprove={async (data) => {
              setBusy(true);
              try {
                await authorize(jobRef.current!.id, data.orderID);
                navigate(`/booked/${jobRef.current!.id}`);
              } catch (e) {
                setBusy(false);
                setError(`Your payment was approved but we couldn't finish the booking: ${(e as Error).message} Please try again; you have not been charged.`);
              }
            }}
            onCancel={() => setError("Payment was cancelled. You have not been charged.")}
            onError={() => setError((e) => e ?? "Something went wrong with PayPal. Please try again.")}
          />
        </PayPalScriptProvider>
      ) : (
        <p className="error">Set VITE_PAYPAL_CLIENT_ID in web/.env to show the PayPal button.</p>
      )}
    </section>
  );
}
