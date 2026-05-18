"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { DashboardSummaryPanels } from "@/components/DashboardSummaryPanels";
import { PageContainer, PageHero } from "@/components/PageContainer";
import RoutePending from "@/components/RoutePending";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";

// /activity — the lists side of DashboardSummaryPanels: recent memories,
// top patterns, top tags, recent sessions. Kept on its own route in
// v0.3.47 so users can bookmark / share the activity view directly.
export default function ActivityPage() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();
  const copy = t.pages.activity;

  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    enabled: !!user,
  });

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

  const projectCount = projects?.length ?? 0;
  const totalMemories = projects?.reduce((sum, p) => sum + p.memory_count, 0) ?? 0;
  const totalKnacks = projects?.reduce((sum, p) => sum + (p.instinct_count ?? 0), 0) ?? 0;

  return (
    <AppShell>
      <PageContainer>
        <PageHero eyebrow={copy.eyebrow} title={copy.title} subtitle={copy.subtitle} />
        <div className="mt-6">
          <DashboardSummaryPanels
            totalMemories={totalMemories}
            totalKnacks={totalKnacks}
            projectCount={projectCount}
            section="activity"
          />
        </div>
      </PageContainer>
    </AppShell>
  );
}
