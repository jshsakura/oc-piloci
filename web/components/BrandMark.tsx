"use client";

import Link from "next/link";

export default function BrandMark({ className }: { className?: string }) {
  return (
    <Link href="/" className={className ?? "inline-flex items-center gap-1.5 font-semibold tracking-tight"}>
      <svg width="24" height="24" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg" className="shrink-0">
        <defs>
          <linearGradient id="brand-bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#020617" />
            <stop offset="100%" stopColor="#0F172A" />
          </linearGradient>
          <linearGradient id="brand-pi" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#00F0FF" />
            <stop offset="50%" stopColor="#7000FF" />
            <stop offset="100%" stopColor="#FF007F" />
          </linearGradient>
        </defs>
        <rect width="256" height="256" rx="64" fill="url(#brand-bg)" />
        <path d="M 60 80 Q 60 70 75 70 H 181 Q 196 70 196 85 V 95 Q 196 105 186 105 H 70 Q 60 105 60 95 Z" fill="url(#brand-pi)" />
        <path d="M 90 105 V 170 Q 90 190 70 190 Q 60 190 60 180 V 175 Q 60 165 70 165 Q 80 165 80 175 V 105 Z" fill="url(#brand-pi)" opacity="0.9" />
        <path d="M 150 105 V 175 Q 150 190 165 190 Q 185 190 195 175 Q 200 165 190 155 Q 180 145 170 155 Q 165 160 165 170 V 105 Z" fill="url(#brand-pi)" />
      </svg>
      <span className="font-[Gugi,sans-serif] text-foreground tracking-wide">piLoci</span>
    </Link>
  );
}
