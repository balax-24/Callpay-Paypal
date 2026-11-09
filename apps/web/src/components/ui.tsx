"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const NAV = [
  ["/", "Overview"],
  ["/calls", "Calls"],
  ["/orders", "Orders"],
  ["/payouts", "Payouts & approvals"],
  ["/analytics", "Ask your business"],
  ["/audit", "Audit log"],
  ["/chaos", "Chaos runs"],
  ["/call", "Try a call"],
] as const;

export function Nav() {
  const path = usePathname();
  return (
    <header className="border-b border-line bg-panel/80 backdrop-blur sticky top-0 z-20">
      <div className="mx-auto max-w-7xl px-4 flex items-center gap-6 h-14 overflow-x-auto">
        <Link href="/" className="font-semibold tracking-tight whitespace-nowrap flex items-center gap-2">
          <span className="inline-grid place-items-center w-7 h-7 rounded-lg bg-brand text-white text-sm">☎</span>
          CallPay
        </Link>
        <nav className="flex gap-1 text-sm">
          {NAV.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={`px-3 py-1.5 rounded-md whitespace-nowrap ${
                path === href ? "bg-brand/10 text-brand font-medium" : "text-muted hover:text-fg hover:bg-fg/5"
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line bg-panel p-4 ${className}`}>
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
    <div className="rounded-xl border border-line bg-panel p-4">
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
