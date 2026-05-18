"use client";

import { ReactNode } from "react";
import AppShell from "@/components/AppShell";
import { PageContainer } from "@/components/PageContainer";
import RoutePending from "@/components/RoutePending";
import { useTranslation } from "@/lib/i18n";
import { usePageGuard } from "@/lib/usePageGuard";

/**
 * Wraps any authenticated dashboard page with the same chrome the
 * summary / activity / pipeline pages used to repeat by hand:
 *   - auth guard (pending → spinner, redirecting → null)
 *   - AppShell with the page title
 *   - PageContainer for the standard max-width
 *
 * Pages with non-standard layouts (memory wiki full-bleed) can skip
 * this wrapper and call AppShell + usePageGuard directly.
 */
interface AuthedPageProps {
  title: string;
  children: ReactNode;
  /** Set false to opt out of the centered max-w container (full-bleed). */
  contained?: boolean;
}

export function AuthedPage({ title, children, contained = true }: AuthedPageProps) {
  const { state } = usePageGuard();
  const { t } = useTranslation();

  if (state === "pending") {
    return (
      <AppShell title={title}>
        <RoutePending title={t.dashboard.pending.title} description={t.dashboard.pending.desc} />
      </AppShell>
    );
  }
  if (state === "redirecting") {
    return (
      <RoutePending
        fullScreen
        title={t.dashboard.redirect.title}
        description={t.dashboard.redirect.desc}
      />
    );
  }

  return (
    <AppShell title={title}>
      {contained ? <PageContainer>{children}</PageContainer> : children}
    </AppShell>
  );
}
