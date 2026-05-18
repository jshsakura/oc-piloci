"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { DistillationStatusPanel } from "@/components/DistillationStatusPanel";
import { PageContainer } from "@/components/PageContainer";
import { RecentSessionsCard } from "@/components/RecentSessionsCard";
import RoutePending from "@/components/RoutePending";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";

// /pipeline — backend ops view: distillation status + recent session
// outcomes (success / failure / filter). Used to live inside dashboard
// as ?panel=ops; promoted to its own route in v0.3.47.
export default function PipelinePage() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();
  const copy = t.pages.pipeline;

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) router.replace("/login");
  }, [hasHydrated, isBootstrapping, router, user]);

  if (!hasHydrated || isBootstrapping) {
    return (
      <AppShell>
        <RoutePending title={t.dashboard.pending.title} description={t.dashboard.pending.desc} />
      </AppShell>
    );
  }
  if (!user) {
    return (
      <RoutePending
        fullScreen
        title={t.dashboard.redirect.title}
        description={t.dashboard.redirect.desc}
      />
    );
  }

  return (
    <AppShell title={copy.title}>
      <PageContainer>
        <div className="space-y-6">
          <DistillationStatusPanel />
          <RecentSessionsCard />
        </div>
      </PageContainer>
    </AppShell>
  );
}
