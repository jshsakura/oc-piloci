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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const MCP_SNIPPET = `{
  "mcpServers": {
    "piloci": {
      "type": "http",
      "url": "https://piloci.example.com/sse",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}`;

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

  if (!slug) return null;

  const selectedNote = notes.find((n) => n.memory_id === selectedNoteId) ?? notes[0] ?? null;
  const stats = data?.workspace.stats;

  return (
    <AppShell>
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.push("/dashboard")}>
          <ArrowLeft className="mr-1 size-4" /> 대시보드
        </Button>
        <span className="text-sm text-muted-foreground">/</span>
        <h1 className="text-xl font-bold">{data?.project.name ?? slug}</h1>
      </div>

      {data?.project.description && (
        <p className="mt-2 text-sm text-muted-foreground">{data.project.description}</p>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">노트</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-bold">{stats?.notes ?? 0}</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">노드</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-bold">{stats?.nodes ?? 0}</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">관계</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-bold">{stats?.edges ?? 0}</p></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm font-medium text-muted-foreground">태그</CardTitle></CardHeader>
          <CardContent><p className="text-2xl font-bold">{stats?.tags ?? 0}</p></CardContent>
        </Card>
      </div>

      <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
        <div>
          <h2 className="mb-4 text-lg font-semibold">노트</h2>
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-32 w-full rounded-lg" />)}
            </div>
          ) : notes.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center gap-3 py-10 text-muted-foreground">
                <FileText className="size-8" />
                <p className="text-sm">노트가 없습니다</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {notes.map((note) => (
                <VaultNoteCard
                  key={note.memory_id}
                  note={note}
                  active={note.memory_id === selectedNote?.memory_id}
                  onSelect={(n) => setSelectedNoteId(n.memory_id)}
                />
              ))}
            </div>
          )}
        </div>
        <VaultNoteDetail note={selectedNote} />
      </div>

      <div className="mt-8">
        <h2 className="mb-4 text-lg font-semibold">MCP 설정</h2>
        <pre className="overflow-x-auto rounded-md bg-muted p-4 font-mono text-sm">{MCP_SNIPPET}</pre>
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
