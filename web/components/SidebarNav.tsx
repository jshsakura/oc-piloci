"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  BookOpenCheck,
  FolderKanban,
  GanttChart,
  MessageSquareText,
  Network,
  UsersRound,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import BrandMark from "@/components/BrandMark";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/i18n";

/**
 * v0.3.46 IA flatten: a single left sidebar replaces the
 * workspace-segment + personal-panel two-level nesting. Every destination
 * the user can reach is a top-level entry here. Mobile uses the same list
 * inside a slide-in drawer triggered by AppShell's hamburger button.
 *
 * Active state matches both pathname and the relevant search params so
 * /dashboard?panel=ops doesn't bleed into the "Summary" row's selection.
 */
export type SidebarMatch = {
  pathname: string;
  search?: Record<string, string>;
};

export interface SidebarItem {
  key: string;
  label: string;
  href: string;
  icon: LucideIcon;
  match: SidebarMatch;
}

function useSidebarItems(): SidebarItem[] {
  const { t } = useTranslation();
  const labels = t.appShell.sidebar;
  return [
    {
      key: "summary",
      label: labels.summary,
      href: "/dashboard",
      icon: BookOpenCheck,
      match: { pathname: "/dashboard", search: { panel: "summary" } },
    },
    {
      key: "memory",
      label: labels.memory,
      href: "/memory",
      icon: Network,
      match: { pathname: "/memory" },
    },
    {
      key: "activity",
      label: labels.activity,
      href: "/dashboard?panel=activity",
      icon: Activity,
      match: { pathname: "/dashboard", search: { panel: "activity" } },
    },
    {
      key: "ops",
      label: labels.ops,
      href: "/dashboard?panel=ops",
      icon: GanttChart,
      match: { pathname: "/dashboard", search: { panel: "ops" } },
    },
    {
      key: "projects",
      label: labels.projects,
      href: "/dashboard?view=projects",
      icon: FolderKanban,
      match: { pathname: "/dashboard", search: { view: "projects" } },
    },
    {
      key: "teams",
      label: labels.teams,
      href: "/dashboard?view=team",
      icon: UsersRound,
      match: { pathname: "/dashboard", search: { view: "team" } },
    },
    {
      key: "chat",
      label: labels.chat,
      href: "/chat",
      icon: MessageSquareText,
      match: { pathname: "/chat" },
    },
  ];
}

function isActive(item: SidebarItem, pathname: string, params: URLSearchParams): boolean {
  if (item.match.pathname !== pathname) return false;
  if (!item.match.search) {
    // Pathname-only entries also need to lose to more-specific rows when
    // /dashboard has a panel/view set — otherwise "Summary" lights up
    // for /dashboard?view=projects.
    if (pathname === "/dashboard") {
      const hasViewOrPanel = params.get("view") || params.get("panel");
      // The summary row carries an explicit {panel: "summary"} match, so
      // no pathname-only entry should ever target /dashboard. Defensive.
      return !hasViewOrPanel;
    }
    return true;
  }
  for (const [k, v] of Object.entries(item.match.search)) {
    if (params.get(k) !== v) {
      // Summary is the implicit default — accept the row when panel/view
      // are absent and the row's expected value matches the default.
      if (k === "panel" && v === "summary" && !params.get("panel") && !params.get("view")) {
        continue;
      }
      return false;
    }
  }
  return true;
}

interface NavListProps {
  items: SidebarItem[];
  pathname: string;
  params: URLSearchParams;
  onNavigate?: () => void;
}

function NavList({ items, pathname, params, onNavigate }: NavListProps) {
  return (
    <nav className="flex flex-col gap-0.5">
      {items.map((item) => {
        const Icon = item.icon;
        const active = isActive(item, pathname, params);
        return (
          <Link
            key={item.key}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "inline-flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            <span className="truncate">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function DesktopSidebar() {
  const pathname = usePathname() || "/";
  const params = useSearchParams();
  const items = useSidebarItems();
  return (
    <aside className="bg-card/40 hidden w-56 shrink-0 flex-col border-r p-3 md:flex">
      <NavList items={items} pathname={pathname} params={params || new URLSearchParams()} />
    </aside>
  );
}

interface MobileDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function MobileSidebarDrawer({ open, onClose }: MobileDrawerProps) {
  const pathname = usePathname() || "/";
  const params = useSearchParams();
  const items = useSidebarItems();

  // Lock background scroll while the drawer is open so a touch flick can't
  // accidentally scroll the page underneath. Also auto-close on `Escape`
  // for keyboard users.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div
        aria-hidden
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="bg-background absolute inset-y-0 start-0 flex w-72 max-w-[85vw] flex-col border-e shadow-xl">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <BrandMark />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className="hover:bg-muted rounded-md p-1.5 transition-colors"
          >
            <X className="size-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <NavList
            items={items}
            pathname={pathname}
            params={params || new URLSearchParams()}
            onNavigate={onClose}
          />
        </div>
      </div>
    </div>
  );
}
