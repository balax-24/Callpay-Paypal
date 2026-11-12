"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

const GROUPS: [string, [string, string][]][] = [
  ["Run the shop", [["/dashboard", "Overview"], ["/calls", "Calls"], ["/orders", "Orders"], ["/menu", "Menu"]]],
  ["Money", [["/payouts", "Payouts & approvals"], ["/reconcile", "Reconcile"], ["/analytics", "Ask your business"]]],
  ["Trust", [["/safety", "Safety & alerts"], ["/audit", "Audit log"], ["/chaos", "Chaos runs"]]],
];

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 font-semibold tracking-tight whitespace-nowrap">
      <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand text-white" aria-hidden>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z" />
        </svg>
      </span>
      CallPay
    </Link>
  );
}

function SideLinks({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  return (
    <nav className="space-y-5">
      {GROUPS.map(([group, links]) => (
        <div key={group}>
          <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted">{group}</div>
          {links.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={path === href ? "page" : undefined}
              className={`block rounded-lg px-3 py-2 text-sm ${
                path === href ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-fg/5 hover:text-fg"
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}

const callButton = "block rounded-lg bg-brand px-3 py-2.5 text-center text-sm font-medium text-white hover:opacity-90";

/** App frame: a marketing header on the landing page, a grouped sidebar everywhere else. */
export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);

  if (path === "/") {
    return (
      <>
        <header className="sticky top-0 z-20 border-b border-line bg-bg/80 backdrop-blur">
          <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4">
            <Logo />
            <div className="flex items-center gap-2">
              <Link href="/dashboard" className="hidden rounded-lg px-3 py-2 text-sm text-muted hover:bg-fg/5 hover:text-fg sm:block">Owner dashboard</Link>
              <Link href="/call" className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:opacity-90">Try a call</Link>
            </div>
          </div>
        </header>
        <main>{children}</main>
      </>
    );
  }

  return (
    <div className="lg:flex">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-line bg-panel p-4 lg:flex">
        <Logo />
        <Link href="/call" className={callButton}>Try a call</Link>
        <SideLinks path={path} />
        <p className="mt-auto px-3 text-[11px] leading-relaxed text-muted">PayPal sandbox demo. No real money moves.</p>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-panel/90 px-4 backdrop-blur lg:hidden">
          <Logo />
          <button onClick={() => setOpen(!open)} aria-expanded={open} aria-label="Menu" className="rounded-lg border border-line px-3 py-1.5 text-sm">
            {open ? "Close" : "Menu"}
          </button>
        </header>
        {open && (
          <div className="space-y-5 border-b border-line bg-panel p-4 lg:hidden">
            <Link href="/call" onClick={() => setOpen(false)} className={callButton}>Try a call</Link>
            <SideLinks path={path} onNavigate={() => setOpen(false)} />
          </div>
        )}
        <main className="mx-auto max-w-7xl px-4 py-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-line bg-panel p-5 shadow-[0_1px_2px_rgb(0_0_0/0.04)] ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between mb-3 gap-2">
          <h2 className="text-sm font-semibold">{title}</h2>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-panel p-5 shadow-[0_1px_2px_rgb(0_0_0/0.04)]">
      <div className="text-xs text-muted">{label}</div>
      <div className="text-2xl font-semibold mt-1 tabular-nums">{value}</div>
      {hint && <div className="text-xs text-muted mt-1">{hint}</div>}
    </div>
  );
}

const TONES: Record<string, string> = {
  green: "bg-ok/15 text-ok", red: "bg-bad/15 text-bad", amber: "bg-warn/15 text-warn",
  blue: "bg-brand/15 text-brand", gray: "bg-fg/10 text-muted",
};

export function Badge({ tone = "gray", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}

export function statusTone(s?: string | null): keyof typeof TONES {
  if (!s) return "gray";
  if (["paid", "ready", "sent", "completed", "closed", "ended", "auto", "approved"].includes(s)) return "green";
  if (["failed", "rejected", "expired", "open", "abandoned", "deny"].includes(s)) return "red";
  if (["pending_approval", "awaiting_payment", "link_sent", "half_open", "approval", "recovered", "preparing"].includes(s)) return "amber";
  return "blue";
}

export function Button({ children, onClick, tone = "default", disabled, small }: {
  children: ReactNode; onClick?: () => void; tone?: "default" | "primary" | "danger"; disabled?: boolean; small?: boolean;
}) {
  const t = tone === "primary" ? "bg-brand text-white hover:bg-brand/90 border-brand"
    : tone === "danger" ? "border-bad/40 text-bad hover:bg-bad/10" : "border-line hover:bg-fg/5";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md border ${small ? "px-2 py-0.5 text-xs" : "px-3 py-1.5 text-sm"} font-medium disabled:opacity-40 ${t}`}
    >
      {children}
    </button>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-md border border-bad/30 bg-bad/10 text-bad text-xs px-3 py-2 mb-3">API: {error}</div>;
}
