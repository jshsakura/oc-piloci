"use client";

import { Suspense, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ClipboardList,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";
import LocaleToggle from "@/components/LocaleToggle";
import { DesktopSidebar, MobileSidebarDrawer } from "@/components/SidebarNav";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";

interface AppShellProps {
  children: React.ReactNode;
  /** Page name shown in the unified top bar (v0.3.53). Leave undefined
   *  on auth/landing screens that have their own chrome. */
  title?: string;
  /** Optional right-aligned page controls (e.g. project selector on
   *  the memory wiki). Rendered inside the top bar so each page no
   *  longer needs its own header row. */
  actions?: React.ReactNode;
}

export default function AppShell({ children, title, actions }: AppShellProps) {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { t } = useTranslation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = async () => {
    try {
      await api.logout();
    } finally {
      logout();
      router.push("/login");
    }
  };

  // v0.3.46 IA: flat left sidebar (desktop) + hamburger drawer (mobile).
  // The top bar shrinks to brand + utility actions; every destination
  // surfaces inside the sidebar so the user can scan the entire app at
  // a glance instead of pivoting through workspace > segment > panel.
  // Sidebar components are wrapped in Suspense because they read
  // useSearchParams (App Router requirement under static export).
  return (
    <div className="bg-background landing-pattern flex min-h-dvh flex-col">
      <header className="bg-background sticky top-0 z-30 border-b">
        <div className="flex h-14 w-full items-center gap-3 px-3 sm:px-6">
          {/* Mobile-only hamburger — desktop uses the persistent sidebar. */}
          <button
            type="button"
            aria-label={t.appShell.sidebar.menuLabel}
            onClick={() => setMobileOpen(true)}
            className="hover:bg-muted -ms-1 rounded-md p-2 md:hidden"
          >
            <Menu className="size-5" />
          </button>
          {/* Brand sits in the top header on desktop only — on mobile the
              hamburger is the obvious entry into the drawer (which carries
              its own BrandMark), so doubling it up in the header just
              eats horizontal space. */}
          <div className="hidden md:block">
            <BrandMark />
          </div>
          {/* Vertical separator before the page title, only when we
              actually have a title (some pages opt out). */}
          {title && (
            <>
              <span className="bg-border hidden h-5 w-px md:inline-block" aria-hidden />
              <h1 className="truncate text-sm font-semibold tracking-tight">{title}</h1>
            </>
          )}
          {actions && (
            // ms-auto pushes both actions and the utility row to the
            // right; utilities sit right after, no extra ms-auto there.
            <div className="ms-auto flex items-center gap-2">{actions}</div>
          )}
          <div className={`${actions ? "" : "ms-auto "}flex shrink-0 items-center gap-1.5`}>
            <LocaleToggle />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="ms-1 flex size-9 cursor-pointer items-center justify-center rounded-full border bg-background/60 transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Avatar className="size-8">
                    <AvatarFallback className="text-xs">
                      {user?.email?.charAt(0).toUpperCase() ?? "U"}
                    </AvatarFallback>
                  </Avatar>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <div className="px-2 py-1.5 text-sm text-muted-foreground select-none">
                  {user?.email}
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/settings">
                    <Settings className="me-2 size-4" />
                    {t.appShell.dropdown.settings}
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href="/audit">
                    <ClipboardList className="me-2 size-4" />
                    {t.appShell.dropdown.activity}
                  </Link>
                </DropdownMenuItem>
                {user?.is_admin && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                      <Link href="/admin/users">
                        <ShieldCheck className="me-2 size-4" />
                        {t.appShell.dropdown.admin}
                      </Link>
                    </DropdownMenuItem>
                  </>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleLogout} className="text-destructive">
                  <LogOut className="me-2 size-4" />
                  {t.appShell.dropdown.logout}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        <Suspense fallback={null}>
          <DesktopSidebar />
        </Suspense>
        <Suspense fallback={null}>
          <MobileSidebarDrawer open={mobileOpen} onClose={() => setMobileOpen(false)} />
        </Suspense>
        {/* main no longer caps width — full-bleed pages (memory wiki) need
            the room; conventional pages opt back in to a max-w container
            by wrapping their own children. */}
        {/* overflow-x-hidden 가드: 어떤 페이지의 내부 요소(긴 path/슬러그/
            mono URL)가 viewport 너비를 넘겨도 모바일에서 좌우 스크롤이
            생기지 않도록. 진짜로 가로 스크롤이 필요한 영역(그래프 등)은
            자체 컨테이너에 overflow-x-auto를 명시하면 정상 동작. */}
        <main className="min-w-0 flex-1 overflow-x-hidden">
          <div className="w-full max-w-full px-4 py-6 sm:px-6 lg:py-8">{children}</div>
        </main>
      </div>

      <footer className="pi-glass-nav border-t [box-shadow:none] backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-11 w-full max-w-7xl items-center justify-between px-4 text-xs text-muted-foreground sm:px-6">
          <p>© piLoci 2026</p>
          <div className="flex items-center gap-4">
            <Link href="/privacy" className="hover:text-foreground transition-colors">
              {t.appShell.footer.privacy}
            </Link>
            <Link href="/terms" className="hover:text-foreground transition-colors">
              {t.appShell.footer.terms}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
