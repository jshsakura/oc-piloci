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
 * Slim, in-flow page header — matches the memory wiki's topbar so every
 * page reads the same. v0.3.52 dropped the large "pi-page-hero" block;
 * the user wanted a single visual idiom across pages, not a one-off
 * card-like hero per page.
 *
 * `eyebrow` is kept on the type for back-compat with callers but is no
 * longer rendered — the title alone is enough at this size.
 */
export function PageHero({
  title,
  subtitle,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-4 flex items-center gap-3 border-b pb-3">
      <div className="flex min-w-0 items-baseline gap-2">
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="text-muted-foreground hidden truncate text-xs sm:block">
            {subtitle}
          </p>
        )}
      </div>
    </div>
  );
}
