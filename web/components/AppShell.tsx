"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { LayoutDashboard, FolderKanban, Settings, ClipboardList, LogOut, ShieldCheck } from "lucide-react";
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
  ];

  if (user?.is_admin) {
    navItems.push({ href: "/admin/users", label: t.admin.title, icon: ShieldCheck });
  }

  const handleLogout = async () => {
    try {
      await api.logout();
    } finally {
      logout();
      router.push("/login");
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-background landing-pattern">
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4">
          <BrandMark />
          <div className="flex items-center gap-1">
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
            <LocaleToggle />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="ml-1 flex size-8 cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                    <Settings className="mr-2 size-4" />
                    {t.appShell.dropdown.settings}
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href="/audit">
                    <ClipboardList className="mr-2 size-4" />
                    {t.appShell.dropdown.activity}
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleLogout} className="text-destructive">
                  <LogOut className="mr-2 size-4" />
                  {t.appShell.dropdown.logout}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
      <footer className="mt-auto border-t bg-background py-2.5">
        <div className="mx-auto flex flex-col items-center gap-2 sm:flex-row sm:justify-between max-w-6xl px-4">
          <p className="text-xs text-muted-foreground">© piLoci 2026</p>
          <div className="flex items-center gap-4">
            <Link href="/privacy" className="text-xs text-muted-foreground/60 hover:text-foreground transition-colors">
              {t.appShell.footer.privacy}
            </Link>
            <Link href="/terms" className="text-xs text-muted-foreground/60 hover:text-foreground transition-colors">
              {t.appShell.footer.terms}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
