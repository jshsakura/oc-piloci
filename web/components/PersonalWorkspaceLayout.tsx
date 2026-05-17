"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, BookOpenCheck, GanttChart, LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/i18n";

/**
 * Sub-navigation inside the personal workspace segment. Sidebar on ≥sm
 * viewports (vertical, persistent), horizontal pill row on mobile so the
 * three panes stay one tap away inside a 360-wide phone.
 *
 * URL contract: ``?view=personal&panel=summary|ops|activity`` — both query
 * keys are managed by the parent dashboard page so deep-link + back-button
 * navigation keeps working across hard reloads.
 */
export type PersonalPanel = "summary" | "ops" | "activity";
const PANELS: PersonalPanel[] = ["summary", "ops", "activity"];

export function isPersonalPanel(value: string | null): value is PersonalPanel {
  return value !== null && (PANELS as string[]).includes(value);
}

export const DEFAULT_PERSONAL_PANEL: PersonalPanel = "summary";

interface Props {
  panel: PersonalPanel;
  children: React.ReactNode;
}

export function PersonalWorkspaceLayout({ panel, children }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const labels = t.dashboard.personalPanels;

  const items: { key: PersonalPanel; label: string; icon: LucideIcon }[] = [
    { key: "summary", label: labels.summary, icon: BookOpenCheck },
    { key: "ops", label: labels.ops, icon: GanttChart },
    { key: "activity", label: labels.activity, icon: Activity },
  ];

  const setPanel = useCallback(
    (next: PersonalPanel) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("view", "personal");
      if (next === DEFAULT_PERSONAL_PANEL) {
        params.delete("panel");
      } else {
        params.set("panel", next);
      }
      const qs = params.toString();
      router.replace(qs ? `/dashboard?${qs}` : "/dashboard");
    },
    [router, searchParams],
  );

  return (
    <div className="flex flex-col gap-4 sm:grid sm:grid-cols-[180px_minmax(0,1fr)]">
      {/* Mobile pill row — sm breakpoint hides this and reveals the sidebar.
          Kept horizontally scrollable so a wider locale (English labels) still
          fits on the smallest viewport. */}
      <nav
        aria-label="개인 워크스페이스 서브 메뉴"
        className="bg-muted/30 -mx-1 flex gap-1 overflow-x-auto rounded-lg p-1 sm:hidden"
      >
        {items.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setPanel(key)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              key === panel
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:bg-background/60",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {label}
          </button>
        ))}
      </nav>

      {/* Desktop sidebar */}
      <nav
        aria-label="개인 워크스페이스 서브 메뉴"
        className="hidden flex-col gap-0.5 sm:flex"
      >
        {items.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setPanel(key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              key === panel
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}
      </nav>

      <div className="min-w-0 space-y-6">{children}</div>
    </div>
  );
}
