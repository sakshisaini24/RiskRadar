import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "RiskRadar AI",
  description: "Multi-Model Consensus Engine for Escalation Risk",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 font-sans">
        <TopNav />
        <main>{children}</main>
      </body>
    </html>
  );
}

function TopNav() {
  return (
    <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-6 md:px-10 py-4 flex items-center justify-between gap-6">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-blue-800 flex items-center justify-center text-white font-black text-sm shadow-md shadow-blue-200">
            R
          </div>
          <div className="leading-tight">
            <div className="text-lg font-black tracking-tight text-blue-900 group-hover:text-blue-700 transition-colors">
              RiskRadar AI
            </div>
            <div className="text-[10px] text-slate-500 font-medium uppercase tracking-widest">
              Escalation Intelligence
            </div>
          </div>
        </Link>

        <div className="flex items-center gap-2">
          <NavLink href="/" icon="📋" label="Triage Queue" />
          <NavLink href="/claim" icon="🔍" label="Single Claim" />
        </div>

        <div className="hidden md:flex items-center gap-2 text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="font-bold">System Online</span>
        </div>
      </div>
    </nav>
  );
}

function NavLink({ href, icon, label }: { href: string; icon: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold text-slate-600 hover:text-blue-700 hover:bg-blue-50 transition-all"
    >
      <span>{icon}</span>
      <span>{label}</span>
    </Link>
  );
}