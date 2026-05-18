"use client";

import { useQuery } from "@tanstack/react-query";
import { AuthedPage } from "@/components/AuthedPage";
import { DashboardSummaryPanels } from "@/components/DashboardSummaryPanels";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";

export default function ActivityPage() {
  const { user } = useAuthStore();
  const { t } = useTranslation();
  const copy = t.pages.activity;

  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    enabled: !!user,
  });

  const projectCount = projects?.length ?? 0;
  const totalMemories = projects?.reduce((sum, p) => sum + p.memory_count, 0) ?? 0;
  const totalKnacks = projects?.reduce((sum, p) => sum + (p.instinct_count ?? 0), 0) ?? 0;

  return (
    <AuthedPage title={copy.title}>
      <DashboardSummaryPanels
        totalMemories={totalMemories}
        totalKnacks={totalKnacks}
        projectCount={projectCount}
        section="activity"
      />
    </AuthedPage>
  );
}
