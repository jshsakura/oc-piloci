"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { LayoutDashboard, Settings, ClipboardList, LogOut, ShieldCheck, MessageSquareText, FolderKanban } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { t } = useTranslation();

  const navItems: { href: string; label: string; icon: typeof LayoutDashboard }[] = [
    { href: "/dashboard", label: t.appShell.nav.dashboard, icon: LayoutDashboard },
    { href: "/projects", label: t.appShell.nav.projects, icon: FolderKanban },
    { href: "/chat", label: t.appShell.nav.chat, icon: MessageSquareText },
  ];

  const handleLogout = async () => {
    try {
      await api.logout();
    } finally {
      logout();
      router.push("/login");
    }
  };

  return (
    <div className="bg-background landing-pattern flex h-screen flex-col overflow-hidden">
      <header className="pi-glass-nav shrink-0 border-b backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
          <BrandMark />
          <div className="flex shrink-0 items-center gap-1.5">
            <nav className="flex items-center gap-1">
              {navItems.map(({ href, label, icon: Icon }) => {
                const active = pathname.startsWith(href);
                return (
                  <Link key={href} href={href}>
                    <Button variant={active ? "secondary" : "ghost"} size="sm" className="gap-1.5 text-sm">
                      <Icon className="size-4" />
                      <span className="hidden sm:inline">{label}</span>
                    </Button>
                  </Link>
                );
              })}
            </nav>
            <span className="mx-1 hidden h-5 w-px bg-border sm:inline-block" />
            <LocaleToggle />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="ms-1 flex size-9 cursor-pointer items-center justify-center rounded-full border bg-background/60 transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Avatar className="size-8">
                    <AvatarFallback className="text-xs">{user?.email?.charAt(0).toUpperCase() ?? "U"}</AvatarFallback>
                  </Avatar>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <div className="px-2 py-1.5 text-sm text-muted-foreground select-none">{user?.email}</div>
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
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:py-8">{children}</div>
      </main>
      <footer className="pi-glass-nav shrink-0 border-t [box-shadow:none] backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
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
