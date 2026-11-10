import { Link } from "react-router-dom";
import { ArrowRight, Camera, Check, Lock, ShieldCheck, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";
import { TIERS } from "../tiers";

const STEPS = [
  { icon: Lock, title: "Book and hold", body: "Pick a clean and approve with PayPal. The amount is held on your account, not charged." },
  { icon: Camera, title: "We clean and prove it", body: "Your cleaner takes before and after photos of every item on your checklist." },
  { icon: ShieldCheck, title: "Pay only when verified", body: "The photos are checked against the checklist. Only then is the payment collected." },
];

// A small product preview built from real components, so the hero shows what the customer will actually see.
function ProofPreview() {
  return (
    <div className="relative mx-auto w-full max-w-sm">
      <div aria-hidden className="absolute -inset-3 -z-10 rounded-3xl bg-accent sm:-inset-6" />
      <div className="rounded-2xl border bg-card p-5 shadow-xs">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm text-muted-foreground">Deep Clean · Sat 10:00</p>
            <p className="font-semibold">1428 Elm Street</p>
          </div>
          <StatusBadge status="RELEASED" />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <div className="flex aspect-[4/3] items-end rounded-lg bg-muted p-2 text-xs font-medium text-muted-foreground">Before</div>
          <div className="flex aspect-[4/3] items-end rounded-lg bg-accent p-2 text-xs font-medium text-accent-foreground">After</div>
        </div>
        <ul className="mt-4 grid gap-2 text-sm">
          {["Kitchen counters wiped", "Bathroom sink and toilet", "Floors vacuumed and mopped"].map((i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="flex size-5 items-center justify-center rounded-full bg-success text-success-foreground">
                <Check className="size-3.5" aria-hidden />
              </span>
              {i}
            </li>
          ))}
        </ul>
        <div className="mt-4 flex items-center justify-between border-t pt-4 text-sm">
          <span className="text-muted-foreground">Verified score</span>
          <span className="font-semibold tabular-nums">0.94</span>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <>
      <section className="mx-auto grid max-w-5xl items-center gap-12 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-sm text-muted-foreground">
            <ShieldCheck className="size-4 text-primary" aria-hidden />
            Pay-on-proof home cleaning
          </p>
          <h1 className="text-4xl font-semibold sm:text-5xl">A spotless home, paid for only when the job is done.</h1>
          <p className="mt-5 max-w-prose text-lg text-muted-foreground">
            Your payment is held on your PayPal account and only collected after the cleaner's before and after photos are verified.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg" className="h-12 px-6 text-base">
              <Link to="/book?tier=deep">Book a clean <ArrowRight aria-hidden /></Link>
            </Button>
            <Button asChild size="lg" variant="outline" className="h-12 px-6 text-base">
              <a href="#pricing">See prices</a>
            </Button>
          </div>
        </div>
        <ProofPreview />
      </section>

      <section aria-labelledby="how" className="border-y bg-card">
        <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6">
          <h2 id="how" className="text-2xl font-semibold sm:text-3xl">How it works</h2>
          <ol className="mt-8 grid gap-8 sm:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title}>
                <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                  <s.icon className="size-5" aria-hidden />
                </span>
                <h3 className="mt-4 font-semibold">
                  <span className="text-muted-foreground tabular-nums">{i + 1}. </span>
                  {s.title}
                </h3>
                <p className="mt-1 text-muted-foreground">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="pricing" aria-labelledby="pricing-h" className="mx-auto max-w-5xl scroll-mt-16 px-4 py-16 sm:px-6 sm:py-24">
        <div className="text-center">
          <h2 id="pricing-h" className="text-2xl font-semibold sm:text-3xl">Choose your clean</h2>
          <p className="mt-2 text-muted-foreground">Flat prices. Held at booking, charged after verification.</p>
        </div>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {TIERS.map((t) => (
            <article
              key={t.id}
              className={cn("relative flex flex-col rounded-xl border bg-card p-6 shadow-xs", t.popular && "border-primary ring-1 ring-primary")}
            >
              {t.popular && (
                <span className="absolute -top-3 left-6 rounded-full bg-honey px-2.5 py-0.5 text-xs font-semibold text-honey-foreground">
                  Most popular
                </span>
              )}
              <h3 className="font-semibold">{t.name}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{t.blurb}</p>
              <p className="mt-6 flex items-baseline gap-1">
                <span className="text-4xl font-semibold tracking-tight tabular-nums">${t.price}</span>
                <span className="text-sm text-muted-foreground">per visit</span>
              </p>
              <ul className="mt-6 grid flex-1 gap-3 text-sm">
                {t.features.map((f) => (
                  <li key={f} className="flex gap-2">
                    <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                    {f}
                  </li>
                ))}
              </ul>
              <Button asChild size="lg" variant={t.popular ? "default" : "outline"} className="mt-8 h-11">
                <Link to={`/book?tier=${t.id}`}>Book {t.name}</Link>
              </Button>
            </article>
          ))}
        </div>
        <p className="mt-8 flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Wallet className="size-4" aria-hidden /> You're never charged for work that isn't verified.
        </p>
      </section>
    </>
  );
}
