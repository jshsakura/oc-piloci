"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { DashboardSummaryPanels } from "@/components/DashboardSummaryPanels";
import { DistillationStatusPanel } from "@/components/DistillationStatusPanel";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";
import RoutePending from "@/components/RoutePending";

export default function DashboardPage() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();

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
      <div className="pi-page-hero">
        <p className="pi-eyebrow">{t.dashboard.eyebrow}</p>
        <h1 className="pi-title mt-2">{t.dashboard.title}</h1>
        <p className="pi-subtitle">{t.dashboard.subtitle}</p>
      </div>

      <DashboardSummaryPanels
        totalMemories={totalMemories}
        totalKnacks={totalKnacks}
        projectCount={projectCount}
      />

      <div className="mt-6">
        <DistillationStatusPanel />
      </div>
    </AppShell>
  );
}
