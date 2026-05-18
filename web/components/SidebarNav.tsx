"use client";

import { useEffect } from "react";
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
      href: "/summary",
      icon: BookOpenCheck,
      match: { pathname: "/summary" },
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
      href: "/activity",
      icon: Activity,
      match: { pathname: "/activity" },
    },
    {
      key: "ops",
      label: labels.ops,
      href: "/pipeline",
      icon: GanttChart,
      match: { pathname: "/pipeline" },
    },
    {
      key: "projects",
      label: labels.projects,
      href: "/projects",
      icon: FolderKanban,
      match: { pathname: "/projects" },
    },
    {
      key: "teams",
      label: labels.teams,
      href: "/teams",
      icon: UsersRound,
      match: { pathname: "/teams" },
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
  // Pages are now distinct routes after v0.3.47 — pathname match is
  // enough. The search-key branch is kept (no-op currently) so callers
  // can still pin sub-state without restructuring the helper.
  if (item.match.pathname !== pathname) return false;
  if (!item.match.search) return true;
  for (const [k, v] of Object.entries(item.match.search)) {
    if (params.get(k) !== v) return false;
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
    // v0.3.49: brand moves into the sidebar header on desktop so the top
    // bar can stay utility-only. bg-background keeps the dot-pattern
    // backdrop from bleeding through.
    <aside className="bg-background hidden w-56 shrink-0 flex-col border-e md:flex">
      <div className="flex h-14 items-center border-b px-4">
        <BrandMark />
      </div>
      <div className="p-3">
        <NavList items={items} pathname={pathname} params={params || new URLSearchParams()} />
      </div>
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
