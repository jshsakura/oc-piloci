import { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Standard page wrapper for "conventional" routes (everything except the
 * memory wiki which wants full bleed). AppShell stopped capping main
 * width in v0.3.47 so each page picks its own max-width and padding.
 * Centralised so we don't sprinkle the same Tailwind chain across every
 * top-level page.
 */
export function PageContainer({
  children,
  className,
  maxWidth = "6xl",
}: {
  children: ReactNode;
  className?: string;
  /** Override the default max-w-6xl; use "none" for full-bleed pages. */
  maxWidth?: "4xl" | "5xl" | "6xl" | "7xl" | "none";
}) {
  const widthClass = {
    "4xl": "max-w-4xl",
    "5xl": "max-w-5xl",
    "6xl": "max-w-6xl",
    "7xl": "max-w-7xl",
    none: "",
  }[maxWidth];
  return <div className={cn("mx-auto w-full", widthClass, className)}>{children}</div>;
}

/**
 * Shared hero block — eyebrow / title / subtitle. Pages render their own
 * so the user always knows which page they landed on (the old "every
 * panel shares the same Dashboard hero" bug).
 */
export function PageHero({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="pi-page-hero">
      <p className="pi-eyebrow">{eyebrow}</p>
      <h1 className="pi-title mt-2">{title}</h1>
      {subtitle && <p className="pi-subtitle">{subtitle}</p>}
    </div>
  );
}
