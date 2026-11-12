import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/field";
import { Page } from "@/components/layout";
import { ErrorAlert } from "@/components/states";
import { setCleanerId } from "@/lib/cleaner-session";
import { todayLocal } from "@/lib/format";
import { Cleaner, listCleaners, signUp } from "../api";

// Matches the API's limits (CleanerCreate in app/schemas.py).
const MAX = { name: 200, email: 320 };
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function CleanerSignup() {
  const navigate = useNavigate();
  const expired = (useLocation().state as { expired?: boolean } | null)?.expired === true;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [touched, setTouched] = useState<{ name?: boolean; email?: boolean }>({});
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState<Cleaner | null>(null);

  // The default demo cleaner has no sign-up, so offer it as a way in.
  useEffect(() => {
    listCleaners(todayLocal())
      .then((all) => setDemo(all.find((c) => c.is_seed) ?? null))
      .catch(() => setDemo(null));
  }, []);

  const errors = {
    name: name.trim() ? undefined : "Enter your name.",
    email: !email.trim()
      ? "Enter your PayPal email."
      : EMAIL.test(email.trim()) ? undefined : "Enter a valid email, like name@example.com.",
  };
  const shown = (k: "name" | "email") => (submitted || touched[k] ? errors[k] : undefined);

  function enter(c: Cleaner) {
    setCleanerId(c.id);
    navigate("/cleaner");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (errors.name || errors.email) return;
    setBusy(true);
    setError(null);
    try {
      enter(await signUp({ name: name.trim(), paypal_email: email.trim() }));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Page>
      <h1 className="text-3xl font-semibold">Become a cleaner</h1>
      <p className="mt-2 text-muted-foreground">
        Sign up to get booked by customers. You're paid to your PayPal account once your photos are verified.
      </p>

      {expired && (
        <p role="status" className="mt-6 rounded-lg bg-warning p-3 text-sm text-warning-foreground">
          That cleaner account has expired, because it wasn't used for 24 hours and demo data is then deleted. Sign up again to continue.
        </p>
      )}

      <form className="mt-8 grid gap-5" noValidate onSubmit={submit}>
        <Field
          id="name"
          label="Your name"
          autoComplete="name"
          maxLength={MAX.name}
          value={name}
          onChange={(e) => { setName(e.target.value); setError(null); }}
          onBlur={() => setTouched((t) => ({ ...t, name: true }))}
          error={shown("name")}
          disabled={busy}
        />
        <Field
          id="email"
          label="PayPal email"
          type="email"
          autoComplete="email"
          maxLength={MAX.email}
          hint="Use a PayPal sandbox account. This is a demo, so no real money moves."
          value={email}
          onChange={(e) => { setEmail(e.target.value); setError(null); }}
          onBlur={() => setTouched((t) => ({ ...t, email: true }))}
          error={shown("email")}
          disabled={busy}
        />
        <p className="text-sm text-muted-foreground">
          Your account stays available for 24 hours after you last use it, then your name and email are deleted.
          Signing up again with the same PayPal email takes you back to your existing account.
        </p>
        {error && <ErrorAlert message={error} />}
        <Button type="submit" size="lg" className="h-11" disabled={busy}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {busy ? "Signing up" : "Sign up"}
        </Button>
      </form>

      {demo && (
        <p className="mt-8 text-sm text-muted-foreground">
          Just looking?{" "}
          <button
            type="button"
            onClick={() => enter(demo)}
            className="rounded font-medium text-primary underline underline-offset-2 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            Continue as {demo.name}
          </button>{" "}
          (the permanent demo cleaner).
        </p>
      )}
      <p className="mt-4 text-sm text-muted-foreground">
        <Link to="/" className="rounded underline underline-offset-2 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none">Back to home</Link>
      </p>
    </Page>
  );
}
