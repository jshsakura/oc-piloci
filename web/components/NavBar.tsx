'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/auth';
import { api } from '@/lib/api';
import { BrandMark } from '@/components/BrandMark';
import { useTranslation } from '@/lib/i18n';
import { Locale } from '@/lib/copy';
import { ThemeToggle } from '@/components/ThemeToggle';
import { Button } from '@/engine/components/ui/button';

interface NavBarProps {
  title?: string;
}

export function NavBar({ title }: NavBarProps) {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { locale, setLocale, t: copy } = useTranslation();

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      // ignore
    } finally {
      logout();
      router.replace('/login');
    }
  };

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-surface-page/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6 gap-4">
        {/* Left: Logo + title */}
        <div className="flex items-center gap-3">
          <Link href="/">
            <BrandMark />
          </Link>

          {title && (
            <>
              <span className="text-border font-light text-lg">/</span>
              <span className="text-[15px] font-medium text-text-secondary tracking-tight">
                {title}
              </span>
            </>
          )}
        </div>

        {/* Right: nav links */}
        <nav className="flex items-center gap-2 sm:gap-4">
          <div className="flex items-center gap-2 mr-2">
            <select
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="bg-transparent text-[11px] font-bold text-text-tertiary outline-none cursor-pointer hover:text-text-primary transition-colors border border-border/50 rounded px-1.5 py-0.5"
            >
              <option value="ko">KO</option>
              <option value="en">EN</option>
            </select>
            <ThemeToggle />
          </div>

          {user ? (
            <>
              <div className="hidden sm:flex items-center gap-1">
                <NavLink href="/dashboard">대시보드</NavLink>
                <NavLink href="/settings">설정</NavLink>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleLogout}
                className="hover:border-destructive hover:text-destructive transition-colors"
              >
                로그아웃
              </Button>
            </>
          ) : (
            <>
              <NavLink href="/login">{copy.common.login}</NavLink>
              <Button size="sm" asChild>
                <Link href="/signup">{copy.common.signup}</Link>
              </Button>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="px-3 py-1.5 rounded-lg text-[13px] font-medium text-text-secondary hover:text-text-primary hover:bg-surface-muted/50 transition-all"
    >
      {children}
    </Link>
  );
}
