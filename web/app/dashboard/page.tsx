"use client";

import { Suspense, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { FolderKanban, LayoutDashboard, UsersRound } from "lucide-react";
import AppShell from "@/components/AppShell";
import { DashboardSummaryPanels } from "@/components/DashboardSummaryPanels";
import { DistillationStatusPanel } from "@/components/DistillationStatusPanel";
import { ProjectListView } from "@/components/ProjectListView";
import { TeamMiniPanel } from "@/components/TeamMiniPanel";
import { WeeklyDigestCard } from "@/components/WeeklyDigestCard";
import RoutePending from "@/components/RoutePending";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";

// Workspace view selector. URL-synced so deep links and back-button history
// keep working — refreshing on the team segment lands you back on the team
// segment, not the personal default.
type View = "personal" | "team" | "projects";
const ALL_VIEWS: View[] = ["personal", "team", "projects"];
const DEFAULT_VIEW: View = "personal";

function isView(value: string | null): value is View {
  return value !== null && (ALL_VIEWS as string[]).includes(value);
}

function DashboardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();

  const viewParam = searchParams.get("view");
  const view: View = isView(viewParam) ? viewParam : DEFAULT_VIEW;

  const onViewChange = useCallback(
    (next: string) => {
      if (!isView(next)) return;
      const params = new URLSearchParams(searchParams.toString());
      if (next === DEFAULT_VIEW) {
        params.delete("view");
      } else {
        params.set("view", next);
      }
      const qs = params.toString();
      router.replace(qs ? `/dashboard?${qs}` : "/dashboard");
    },
    [router, searchParams],
  );

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

      <Tabs value={view} onValueChange={onViewChange} className="mt-6">
        {/* Segment toggle — replaces the old top-nav split. Full-width on mobile
            so all three labels stay reachable inside the cramped 360px viewport. */}
        <TabsList className="grid w-full grid-cols-3 sm:w-auto sm:inline-flex">
          <TabsTrigger value="personal" className="gap-1.5">
            <LayoutDashboard className="size-3.5" aria-hidden />
            <span>{t.dashboard.segments.personal}</span>
          </TabsTrigger>
          <TabsTrigger value="team" className="gap-1.5">
            <UsersRound className="size-3.5" aria-hidden />
            <span>{t.dashboard.segments.team}</span>
          </TabsTrigger>
          <TabsTrigger value="projects" className="gap-1.5">
            <FolderKanban className="size-3.5" aria-hidden />
            <span>{t.dashboard.segments.projects}</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="personal" className="mt-6 space-y-6">
          {/* The private retrospective belongs to the personal segment only —
              feedback memories must never surface alongside team material. */}
          <WeeklyDigestCard />
          <DashboardSummaryPanels
            totalMemories={totalMemories}
            totalKnacks={totalKnacks}
            projectCount={projectCount}
          />
          <DistillationStatusPanel />
        </TabsContent>

        <TabsContent value="team" className="mt-6">
          <TeamMiniPanel />
        </TabsContent>

        <TabsContent value="projects" className="mt-6">
          <ProjectListView />
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}

export default function DashboardPage() {
  // useSearchParams requires Suspense at the App Router level.
  return (
    <Suspense fallback={null}>
      <DashboardContent />
    </Suspense>
  );
}
