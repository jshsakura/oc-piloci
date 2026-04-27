"use client";

import Link from "next/link";

export default function BrandMark({ className }: { className?: string }) {
  return (
    <Link href="/" className={className ?? "inline-flex items-center gap-1.5 font-semibold tracking-tight"}>
      <svg width="24" height="24" viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg" className="shrink-0 text-primary">
        <circle cx="20" cy="18" r="12" fill="currentColor" opacity="0.15" />
        <circle cx="20" cy="18" r="7" fill="currentColor" />
        <line x1="20" y1="25" x2="20" y2="34" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        <circle cx="20" cy="36" r="2" fill="currentColor" />
      </svg>
      <span className="font-[Gugi,sans-serif] text-foreground tracking-wide">piLoci</span>
    </Link>
  );
}
