'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams, useRouter } from 'next/navigation';
import { Card, CardHeader, CardTitle, CardContent } from '@/engine/components/ui/card';
import { Button } from '@/engine/components/ui/button';
import { Badge } from '@/engine/components/ui/badge';
import { EmptyState } from '@/engine/components/patterns/empty-state';
import { PageShell, PageContent } from '@/engine/components/patterns/page-shell';
import { Skeleton } from '@/engine/components/ui/skeleton';
import { api } from '@/lib/api';

const MCP_SNIPPET = `{
  "mcpServers": {
    "piloci": {
      "type": "http",
      "url": "https://piloci.jshsakura.com/sse",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}`;

function ProjectDetailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const slug = searchParams.get('slug');
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) {
      router.replace('/dashboard');
    }
  }, [slug, router]);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['project-workspace', slug],
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
    return null;
  }

  const selectedNote = notes.find((note) => note.memory_id === selectedNoteId) ?? notes[0] ?? null;
  const relationSummary = useMemo(() => {
    if (!selectedNote) {
      return [] as string[];
    }
    return [...selectedNote.tags.map((tag) => `#${tag}`), ...selectedNote.links.map((link) => `[[${link}]]`)];
  }, [selectedNote]);

  return (
    <PageShell maxWidth="896px">
      <PageContent className="px-4 py-8 space-y-6">
        <div className="flex items-center gap-4">
          <Button
            variant="outline"
            size="icon"
            onClick={() => router.push('/dashboard')}
            aria-label="뒤로 가기"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </Button>
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-2xl font-bold text-text-primary truncate">{data?.project.name ?? slug}</h1>
            <Badge variant="outline" className="flex-shrink-0 font-mono">
              {slug}
            </Badge>
          </div>
        </div>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base font-semibold">Vault workspace</CardTitle>
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                새로고침
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : isError ? (
              <div className="text-sm text-destructive">워크스페이스를 불러오지 못했습니다.</div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="rounded-xl border border-border p-4 bg-surface-page">
                  <div className="text-xs text-text-secondary">노트</div>
                  <div className="mt-1 text-2xl font-semibold text-text-primary">{data?.workspace.stats.notes ?? 0}</div>
                </div>
                <div className="rounded-xl border border-border p-4 bg-surface-page">
                  <div className="text-xs text-text-secondary">그래프 노드</div>
                  <div className="mt-1 text-2xl font-semibold text-text-primary">{data?.workspace.stats.nodes ?? 0}</div>
                </div>
                <div className="rounded-xl border border-border p-4 bg-surface-page">
                  <div className="text-xs text-text-secondary">관계선</div>
                  <div className="mt-1 text-2xl font-semibold text-text-primary">{data?.workspace.stats.edges ?? 0}</div>
                </div>
                <div className="rounded-xl border border-border p-4 bg-surface-page">
                  <div className="text-xs text-text-secondary">Vault root</div>
                  <div className="mt-1 text-sm font-mono text-text-primary break-all">{data?.workspace.root ?? '-'}</div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold">브라우저 vault view</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="grid gap-4 lg:grid-cols-[280px,1fr]">
                <Skeleton className="h-72 w-full" />
                <Skeleton className="h-72 w-full" />
              </div>
            ) : notes.length === 0 ? (
              <EmptyState
                title="메모리가 없습니다"
                description="메모리가 저장되면 여기서 Obsidian 스타일 노트와 관계 그래프를 바로 볼 수 있습니다."
              />
            ) : (
              <div className="grid gap-4 lg:grid-cols-[280px,1fr]">
                <div className="space-y-3">
                  {notes.map((note) => {
                    const active = note.memory_id === selectedNote?.memory_id;
                    return (
                      <button
                        key={note.memory_id}
                        type="button"
                        onClick={() => setSelectedNoteId(note.memory_id)}
                        className={`w-full text-left rounded-xl border p-4 transition ${active ? 'border-brand bg-brand/6' : 'border-border bg-surface-page hover:border-brand/40'}`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="font-medium text-text-primary truncate">{note.title}</div>
                            <div className="text-xs text-text-secondary font-mono mt-1 truncate">{note.path}</div>
                          </div>
                          <Badge variant="outline">{note.tags.length}</Badge>
                        </div>
                        <p className="mt-3 text-sm text-text-secondary line-clamp-3">{note.excerpt || '내용 없음'}</p>
                      </button>
                    );
                  })}
                </div>

                <div className="space-y-4">
                  <div className="rounded-xl border border-border p-4 bg-surface-page">
                    <div className="flex flex-wrap items-center gap-2 mb-3">
                      <h2 className="text-lg font-semibold text-text-primary">{selectedNote?.title}</h2>
                      {selectedNote?.tags.map((tag) => (
                        <Badge key={tag} variant="outline">#{tag}</Badge>
                      ))}
                    </div>
                    <p className="text-xs text-text-secondary font-mono">{selectedNote?.path}</p>
                    <pre className="mt-4 whitespace-pre-wrap break-words text-sm text-text-primary font-mono leading-6">{selectedNote?.markdown}</pre>
                  </div>

                  <div className="rounded-xl border border-border p-4 bg-surface-page">
                    <h3 className="text-sm font-semibold text-text-primary mb-3">Graph relationships</h3>
                    {relationSummary.length === 0 ? (
                      <p className="text-sm text-text-secondary">이 노트에는 아직 태그나 위키 링크가 없습니다.</p>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {relationSummary.map((item) => (
                          <Badge key={item} variant="outline">{item}</Badge>
                        ))}
                      </div>
                    )}
                    <div className="mt-4 text-xs text-text-secondary">
                      생성 시각: {data?.workspace.generated_at}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold">MCP 연결 설정</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="rounded-xl border border-border overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-page">
                <span className="text-xs text-text-secondary font-mono">.claude/settings.json</span>
                <span className="text-xs text-text-secondary">JSON</span>
              </div>
              <pre className="p-4 text-xs font-mono text-text-primary bg-surface-page overflow-x-auto leading-relaxed">
                {MCP_SNIPPET}
              </pre>
            </div>
          </CardContent>
        </Card>
      </PageContent>
    </PageShell>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense
      fallback={
        <PageShell maxWidth="896px">
          <PageContent className="px-4 py-8">
            <Skeleton className="h-8 w-48 mb-6" />
            <Skeleton className="h-32 w-full mb-4" />
            <Skeleton className="h-48 w-full" />
          </PageContent>
        </PageShell>
      }
    >
      <ProjectDetailContent />
    </Suspense>
  );
}
