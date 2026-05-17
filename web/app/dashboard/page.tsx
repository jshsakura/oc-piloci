"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { DashboardSummaryPanels } from "@/components/DashboardSummaryPanels";
import { DistillationStatusPanel } from "@/components/DistillationStatusPanel";
import { ProjectListView } from "@/components/ProjectListView";
import { RecentSessionsCard } from "@/components/RecentSessionsCard";
import { TeamMiniPanel } from "@/components/TeamMiniPanel";
import { WeeklyDigestCard } from "@/components/WeeklyDigestCard";
import RoutePending from "@/components/RoutePending";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";

// /dashboard is the polymorphic landing for the personal workspace. Sidebar
// nav (added in v0.3.46) decides which panel to show through ?view= and
// ?panel= — no more in-page segment tabs or nested PersonalWorkspaceLayout.
// Default (no params) = the "Summary" pane.
type View = "personal" | "team" | "projects";
type Panel = "summary" | "ops" | "activity";

function pickView(value: string | null): View {
  if (value === "team" || value === "projects") return value;
  return "personal";
}

function pickPanel(value: string | null): Panel {
  if (value === "ops" || value === "activity") return value;
  return "summary";
}

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();

  const view = pickView(searchParams.get("view"));
  const panel = pickPanel(searchParams.get("panel"));

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

      <div className="mt-6 space-y-6">
        {view === "team" && <TeamMiniPanel />}
        {view === "projects" && <ProjectListView />}
        {view === "personal" && panel === "summary" && (
          <>
            <WeeklyDigestCard />
            <DashboardSummaryPanels
              totalMemories={totalMemories}
              totalKnacks={totalKnacks}
              projectCount={projectCount}
              section="overview"
            />
          </>
        )}
        {view === "personal" && panel === "ops" && (
          <>
            <DistillationStatusPanel />
            <RecentSessionsCard />
          </>
        )}
        {view === "personal" && panel === "activity" && (
          <DashboardSummaryPanels
            totalMemories={totalMemories}
            totalKnacks={totalKnacks}
            projectCount={projectCount}
            section="activity"
          />
        )}
      </div>
    </AppShell>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={null}>
      <DashboardContent />
    </Suspense>
  );
}
