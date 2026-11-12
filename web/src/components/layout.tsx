import { Link } from "react-router-dom";
import { ShieldCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-lg font-semibold tracking-tight focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Sparkles className="size-4" aria-hidden />
      </span>
      <span>Sparkle &amp; Shine</span>
    </Link>
  );
}

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4 sm:px-6">
          <Logo />
          <nav aria-label="Main" className="flex items-center gap-1">
            <Button asChild variant="ghost" className="hidden sm:inline-flex">
              <Link to="/cleaner">For cleaners</Link>
            </Button>
            <Button asChild>
              <Link to="/book">Book a clean</Link>
            </Button>
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-primary" aria-hidden />
            Payments secured by ProofPay: you're only charged once the work is verified.
          </p>
          <p>Demo site · PayPal sandbox, no real money moves. Demo accounts are deleted after 24 hours without use.</p>
        </div>
      </footer>
    </div>
  );
}

// Standard page shell for the narrow (form and job) pages.
export function Page({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto w-full max-w-xl px-4 py-8 sm:px-6 sm:py-12">{children}</div>;
}
