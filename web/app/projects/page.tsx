"use client";

import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, FileText } from "lucide-react";
import AppShell from "@/components/AppShell";
import { ProjectListView } from "@/components/ProjectListView";
import { VaultNoteCard } from "@/components/VaultNoteCard";
import { VaultNoteDetail } from "@/components/VaultNoteDetail";
import { ProjectKnacksPanel } from "@/components/ProjectKnacksPanel";
import { ProjectSessionsPanel } from "@/components/ProjectSessionsPanel";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1.5 rounded-full border bg-card px-3 py-1 shadow-sm">
      <span className="text-base font-semibold tabular-nums">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function ProjectDetailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const slug = searchParams.get("slug");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["project-workspace", slug],
    queryFn: () => api.projectWorkspace(slug as string),
    enabled: Boolean(slug),
  });

  const notes = data?.workspace.notes ?? [];

  useEffect(() => {
    if (!selectedNoteId && notes.length > 0) {
      setSelectedNoteId(notes[0].memory_id);
    }
  }, [notes, selectedNoteId]);

  if (!slug) {
    return (
      <AppShell>
        <ProjectListView />
      </AppShell>
    );
  }

  const selectedNote = notes.find((n) => n.memory_id === selectedNoteId) ?? notes[0] ?? null;
  const stats = data?.workspace.stats;

  return (
    <AppShell>
      <header className="flex flex-col gap-2 border-b pb-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" className="-ml-2" onClick={() => router.push("/projects")}>
            <ArrowLeft className="mr-1 size-4" /> {t.projects.breadcrumb}
          </Button>
          <span className="text-sm text-muted-foreground">/</span>
          <h1 className="truncate text-xl font-semibold tracking-tight">
            {data?.project.name ?? slug}
          </h1>
        </div>
        {data?.project.description && (
          <p className="text-sm text-muted-foreground">{data.project.description}</p>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          <StatChip label={t.projects.notes} value={stats?.notes ?? 0} />
          <StatChip label={t.projects.nodes} value={stats?.nodes ?? 0} />
          <StatChip label={t.projects.edges} value={stats?.edges ?? 0} />
          <StatChip label={t.projects.tags} value={stats?.tags ?? 0} />
        </div>
      </header>

      {/* Inner tabs — keep top-level menu minimal, surface
          memories / patterns / raw sessions inside the project view. */}
      <Tabs defaultValue="memories" className="mt-6">
        <TabsList className="w-full sm:w-auto">
          <TabsTrigger value="memories" className="flex-1 sm:flex-none">
            {t.projects.tabMemories}
          </TabsTrigger>
          <TabsTrigger value="patterns" className="flex-1 sm:flex-none">
            {t.projects.tabKnacks}
          </TabsTrigger>
          <TabsTrigger value="sessions" className="flex-1 sm:flex-none">
            {t.projects.tabSessions}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="memories" className="mt-4">
          <Card className="overflow-hidden lg:h-[calc(100vh-15rem)]">
            <div className="grid h-full lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
              <aside className="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r">
                <div className="flex-1 space-y-2 overflow-y-auto p-3">
                  {isLoading ? (
                    [1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-20 w-full rounded-lg" />)
                  ) : notes.length === 0 ? (
                    <div className="flex flex-col items-center gap-3 py-10 text-muted-foreground">
                      <FileText className="size-8" />
                      <p className="text-sm">{t.projects.noNotes}</p>
                    </div>
                  ) : (
                    notes.map((note) => (
                      <VaultNoteCard
                        key={note.memory_id}
                        note={note}
                        active={note.memory_id === selectedNote?.memory_id}
                        onSelect={(n) => setSelectedNoteId(n.memory_id)}
                      />
                    ))
                  )}
                </div>
              </aside>

              <section className="min-h-0 overflow-y-auto">
                <VaultNoteDetail note={selectedNote} />
              </section>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="patterns" className="mt-4">
          <ProjectKnacksPanel slug={slug} />
        </TabsContent>

        <TabsContent value="sessions" className="mt-4">
          <ProjectSessionsPanel slug={slug} />
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background p-12">
          <Skeleton className="mb-6 h-8 w-48" />
          <Skeleton className="mb-4 h-32 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      }
    >
      <ProjectDetailContent />
    </Suspense>
  );
}
