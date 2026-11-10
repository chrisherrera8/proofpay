import { useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, ChevronLeft, CircleCheck, ShieldCheck } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Field } from "@/components/field";
import { cn } from "@/lib/utils";
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
    <Field
      id={k}
      label={label}
      {...props}
      value={form[k]}
      onChange={set(k)}
      onBlur={blur(k)}
      error={shown(k)}
      disabled={busy}
    />
  );

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
      <Link to="/" className="inline-flex items-center gap-1 rounded text-sm text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none">
        <ChevronLeft className="size-4" aria-hidden /> Back
      </Link>
      <h1 className="mt-3 text-3xl font-semibold">Book a clean</h1>
      <p className="mt-2 text-muted-foreground">Nothing is charged today. PayPal holds the amount until the work is verified.</p>

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[1fr_380px]">
        <div className="grid gap-6">
          <section aria-labelledby="svc" className="rounded-xl border bg-card p-5 shadow-xs sm:p-6">
            <h2 id="svc" className="font-semibold">1. Choose a service</h2>
            <div role="radiogroup" aria-labelledby="svc" className="mt-4 grid gap-3 sm:grid-cols-3">
              {TIERS.map((t) => {
                const active = t.id === tier.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    disabled={busy}
                    onClick={() => setParams({ tier: t.id })}
                    className={cn(
                      "flex min-h-11 items-center justify-between gap-2 rounded-lg border bg-card px-4 py-3 text-left transition-colors outline-none hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-col sm:items-start",
                      active && "border-primary bg-accent ring-1 ring-primary hover:bg-accent",
                    )}
                  >
                    <span className={cn("text-sm font-medium", active && "text-accent-foreground")}>{t.name}</span>
                    <span className="flex items-center gap-2 text-sm text-muted-foreground tabular-nums">
                      ${t.price}
                      {active && <CircleCheck className="size-4 text-primary sm:hidden" aria-hidden />}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section aria-labelledby="details" className="rounded-xl border bg-card p-5 shadow-xs sm:p-6">
            <h2 id="details" className="font-semibold">2. Your details</h2>
            <form className="mt-4 grid gap-5 sm:grid-cols-2" noValidate onSubmit={(e) => e.preventDefault()}>
              {field("name", "Full name", { autoComplete: "name", maxLength: MAX.name })}
              {field("email", "Email", { type: "email", autoComplete: "email", maxLength: MAX.email })}
              <div className="sm:col-span-2">{field("address", "Address", { autoComplete: "street-address", maxLength: MAX.address })}</div>
              {field("when", "Date and time", { type: "datetime-local", min: nowLocal() })}
            </form>
          </section>
        </div>

        <aside aria-labelledby="summary" className="rounded-xl border bg-card p-5 shadow-xs sm:p-6 lg:sticky lg:top-24">
          <h2 id="summary" className="font-semibold">3. Review and pay</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{tier.name}</dt>
              <dd className="tabular-nums">${tier.price}.00</dd>
            </div>
            <div className="flex justify-between gap-4 border-t pt-3 text-base font-semibold">
              <dt>Held today</dt>
              <dd className="tabular-nums">${tier.price}.00</dd>
            </div>
          </dl>
          <p className="mt-4 flex gap-2 rounded-lg bg-accent p-3 text-sm text-accent-foreground">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
            You're charged only after your cleaner's photos are verified.
          </p>

          {error && (
            <Alert variant="destructive" className="mt-4">
              <AlertCircle aria-hidden />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="mt-5">
            {CLIENT_ID ? (
              <PayPalScriptProvider options={{ clientId: CLIENT_ID, intent: "authorize", currency: "USD" }}>
                <PayPalButtons
                  style={{ layout: "vertical", shape: "rect", height: 44 }}
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
              <Alert variant="destructive">
                <AlertCircle aria-hidden />
                <AlertDescription>Set VITE_PAYPAL_CLIENT_ID in web/.env to show the PayPal button.</AlertDescription>
              </Alert>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
