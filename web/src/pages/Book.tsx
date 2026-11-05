import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PayPalButtons, PayPalScriptProvider } from "@paypal/react-paypal-js";
import { authorize, createJob, createOrder } from "../api";
import { TIERS, tierById } from "../tiers";

const CLIENT_ID = import.meta.env.VITE_PAYPAL_CLIENT_ID as string | undefined;

export default function Book() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const tier = tierById(params.get("tier")) ?? TIERS[0];
  const [form, setForm] = useState({ name: "", email: "", address: "", when: "" });
  const [error, setError] = useState<string | null>(null);
  // Buttons keep the callbacks from first render, so read the latest form and job via refs.
  const formRef = useRef(form);
  formRef.current = form;
  const tierRef = useRef(tier);
  tierRef.current = tier;
  const jobRef = useRef<{ id: string; tier: string } | null>(null);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const valid = () => {
    const f = formRef.current;
    return f.name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email) && f.address.trim() && f.when;
  };

  async function makeOrder() {
    const f = formRef.current;
    const t = tierRef.current;
    // Reuse the job if the buyer retries the same tier; the order endpoint is idempotent per job.
    if (!jobRef.current || jobRef.current.tier !== t.id) {
      const job = await createJob({
        customer_name: f.name.trim(),
        customer_email: f.email.trim(),
        address: f.address.trim(),
        service_type: t.id,
        scheduled_at: new Date(f.when).toISOString(),
        amount: t.price,
      });
      jobRef.current = { id: job.id, tier: t.id };
    }
    return (await createOrder(jobRef.current.id)).order_id;
  }

  return (
    <section className="section narrow">
      <h2>Book a clean</h2>
      <div className="tier-pick">
        {TIERS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`pick${t.id === tier.id ? " active" : ""}`}
            onClick={() => setParams({ tier: t.id })}
          >
            {t.name} · ${t.price}
          </button>
        ))}
      </div>

      <form className="form" onSubmit={(e) => e.preventDefault()}>
        <label>Full name<input value={form.name} onChange={set("name")} autoComplete="name" /></label>
        <label>Email<input type="email" value={form.email} onChange={set("email")} autoComplete="email" /></label>
        <label>Address<input value={form.address} onChange={set("address")} autoComplete="street-address" /></label>
        <label>Date and time<input type="datetime-local" value={form.when} onChange={set("when")} /></label>
      </form>

      <p className="total">Total today: <strong>${tier.price}.00</strong> <span className="muted">(authorized now, charged after the job is verified)</span></p>
      {error && <p className="error">{error}</p>}

      {CLIENT_ID ? (
        <PayPalScriptProvider options={{ clientId: CLIENT_ID, intent: "authorize", currency: "USD" }}>
          <PayPalButtons
            style={{ layout: "vertical" }}
            onClick={(_, actions) => {
              if (valid()) { setError(null); return actions.resolve(); }
              setError("Please fill in every field before paying.");
              return actions.reject();
            }}
            createOrder={() => makeOrder()}
            onApprove={async (data) => {
              try {
                await authorize(jobRef.current!.id, data.orderID);
                navigate(`/booked/${jobRef.current!.id}`);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
            onCancel={() => setError("Payment was cancelled. You have not been charged.")}
            onError={(e) => setError(e instanceof Error ? e.message : "Something went wrong with PayPal.")}
          />
        </PayPalScriptProvider>
      ) : (
        <p className="error">Set VITE_PAYPAL_CLIENT_ID in web/.env to show the PayPal button.</p>
      )}
    </section>
  );
}
