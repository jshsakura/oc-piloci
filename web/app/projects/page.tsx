"use client";

import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, FileText } from "lucide-react";
import AppShell from "@/components/AppShell";
import { VaultNoteCard } from "@/components/VaultNoteCard";
import { VaultNoteDetail } from "@/components/VaultNoteDetail";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import RoutePending from "@/components/RoutePending";
import { Skeleton } from "@/components/ui/skeleton";

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
  const slug = searchParams.get("slug");
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) router.replace("/dashboard");
  }, [router, slug]);

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
      <RoutePending
        title="프로젝트 위치 확인 중"
        description="열어야 할 프로젝트를 찾는 중이며, 정보가 없으면 대시보드로 돌아갑니다."
      />
    );
  }

  const selectedNote = notes.find((n) => n.memory_id === selectedNoteId) ?? notes[0] ?? null;
  const stats = data?.workspace.stats;

  return (
    <AppShell>
      <header className="flex flex-col gap-2 border-b pb-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" className="-ml-2" onClick={() => router.push("/dashboard")}>
            <ArrowLeft className="mr-1 size-4" /> 대시보드
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
          <StatChip label="노트" value={stats?.notes ?? 0} />
          <StatChip label="노드" value={stats?.nodes ?? 0} />
          <StatChip label="관계" value={stats?.edges ?? 0} />
          <StatChip label="태그" value={stats?.tags ?? 0} />
        </div>
      </header>

      {/*
        2-column workspace. Both columns claim the same height (calc keeps the
        viewport-minus-header math in one place) and scroll independently so the
        list never pushes the detail pane around.
      */}
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] lg:h-[calc(100vh-15rem)]">
        <aside className="flex min-h-0 flex-col">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold tracking-tight">노트</h2>
            <span className="text-xs text-muted-foreground">{notes.length}</span>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto pr-1">
            {isLoading ? (
              [1, 2, 3].map((i) => <Skeleton key={i} className="h-32 w-full rounded-lg" />)
            ) : notes.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-10 text-muted-foreground">
                  <FileText className="size-8" />
                  <p className="text-sm">노트가 없습니다</p>
                </CardContent>
              </Card>
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

        <section className="min-h-0 lg:overflow-y-auto">
          <VaultNoteDetail note={selectedNote} />
        </section>
      </div>
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
