"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Loader2, RefreshCcw, Sparkles } from "lucide-react";

import AppShell from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { WikiMiniMap } from "@/components/WikiMiniMap";
import { api } from "@/lib/api";
import type { GraphNode, TeamWikiArticle, TeamWikiArticleSummary } from "@/lib/types";

// Article-centric view. List on the left, reader on the right.
// Graph + folder tree intentionally deferred to keep the surface focused.

function resolveWikilinks(markdown: string, articles: TeamWikiArticleSummary[]): string {
  // Replace [[topic]] with markdown links to /teams/{id}/wiki/{slug} when a
  // matching slug exists; otherwise render as plain text in italics so the
  // user sees the intended link without breaking navigation.
  const titleMap = new Map(articles.map((a) => [a.title.toLowerCase(), a.slug]));
  return markdown.replace(/\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]/g, (_, raw, alias) => {
    const label = (alias || raw).trim();
    const slug = titleMap.get(raw.trim().toLowerCase());
    if (slug) return `[${label}](#article-${slug})`;
    return `*${label}*`;
  });
}

function ArticleListSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3, 4].map((i) => (
        <Skeleton key={i} className="h-14 rounded-xl" />
      ))}
    </div>
  );
}

export default function TeamWikiPage() {
  // useSearchParams() requires Suspense at static-export time. The shell does
  // the data-fetching itself so the fallback can be a thin skeleton.
  return (
    <Suspense fallback={<AppShell title="팀 위키"><p className="text-sm text-muted-foreground">불러오는 중…</p></AppShell>}>
      <TeamWikiContent />
    </Suspense>
  );
}

function TeamWikiContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const teamId = searchParams?.get("id") ?? "";
  const queryClient = useQueryClient();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const teamQuery = useQuery({
    queryKey: ["team", teamId],
    queryFn: () => api.getTeam(teamId),
    enabled: Boolean(teamId),
  });

  const articlesQuery = useQuery({
    queryKey: ["team-wiki-articles", teamId],
    queryFn: () => api.listTeamWikiArticles(teamId),
    enabled: Boolean(teamId),
  });

  const workspaceQuery = useQuery({
    queryKey: ["team-workspace", teamId],
    queryFn: () => api.getTeamWorkspace(teamId),
    enabled: Boolean(teamId),
  });

  const articles = articlesQuery.data ?? [];

  // Auto-select the first article when the list arrives so the reader pane
  // isn't blank on first load.
  useEffect(() => {
    if (!selectedSlug && articles.length > 0) {
      setSelectedSlug(articles[0].slug);
    }
  }, [articles, selectedSlug]);

  const articleQuery = useQuery<TeamWikiArticle>({
    queryKey: ["team-wiki-article", teamId, selectedSlug],
    queryFn: () => api.getTeamWikiArticle(teamId, selectedSlug as string),
    enabled: Boolean(teamId && selectedSlug),
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildTeamWiki(teamId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team-wiki-articles", teamId] });
      queryClient.invalidateQueries({ queryKey: ["team", teamId] });
    },
  });

  const toggleAutoMutation = useMutation({
    mutationFn: (next: boolean) =>
      api.patchTeamSettings(teamId, { auto_wiki_enabled: next }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team", teamId] });
    },
  });

  const grouped = useMemo(() => {
    const buckets = new Map<string, TeamWikiArticleSummary[]>();
    for (const article of articles) {
      const key = article.category || "기타";
      const arr = buckets.get(key) ?? [];
      arr.push(article);
      buckets.set(key, arr);
    }
    return Array.from(buckets.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [articles]);

  const isOwner =
    teamQuery.data?.members?.some(
      (m) => m.user_id === teamQuery.data?.owner_id && m.role === "owner",
    ) ?? false;

  const articleContent = articleQuery.data
    ? resolveWikilinks(articleQuery.data.content, articles)
    : "";

  // Map article.sources (id/kind) to graph node ids so the mini-map can
  // ring the source nodes when an article opens.
  const highlightedNodeIds = useMemo(() => {
    const sources = articleQuery.data?.sources ?? [];
    return sources.map((s) =>
      s.kind === "doc" ? `doc:${s.id}` : `memory:${s.id}`,
    );
  }, [articleQuery.data]);

  // Click on a graph node — if it matches an article title, jump to it.
  const handleNodeClick = (node: GraphNode) => {
    if (node.kind === "doc" && node.download_url) {
      window.open(node.download_url, "_blank");
      return;
    }
    if (node.kind === "topic" || node.kind === "note") {
      const lower = node.label.toLowerCase();
      const match = articles.find((a) => a.title.toLowerCase() === lower);
      if (match) setSelectedSlug(match.slug);
    }
  };

  const buildSummary = buildMutation.data;
  const buildError = buildSummary && !buildSummary.success ? buildSummary.error : null;

  return (
    <AppShell title={teamQuery.data?.name ? `${teamQuery.data.name} · 위키` : "팀 위키"}>
      {workspaceQuery.data?.graph && (
        <WikiMiniMap
          nodes={workspaceQuery.data.graph.nodes as GraphNode[]}
          edges={workspaceQuery.data.graph.edges as never}
          highlightedIds={highlightedNodeIds}
          onNodeClick={handleNodeClick}
        />
      )}
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            팀이 쌓아둔 메모와 문서를 GLM이 한국어 위키 아티클로 정리합니다.
          </p>
          {teamQuery.data?.last_wiki_built_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              마지막 생성: {new Date(teamQuery.data.last_wiki_built_at).toLocaleString("ko-KR")}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="size-3.5 accent-primary"
              checked={Boolean(teamQuery.data?.auto_wiki_enabled)}
              disabled={!isOwner || toggleAutoMutation.isPending}
              onChange={(event) => toggleAutoMutation.mutate(event.target.checked)}
            />
            AI 위키 자동 생성 (새벽 1회)
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={() => articlesQuery.refetch()}
            disabled={articlesQuery.isFetching}
          >
            <RefreshCcw className="me-2 size-4" /> 새로고침
          </Button>
          <Button
            size="sm"
            onClick={() => buildMutation.mutate()}
            disabled={buildMutation.isPending || !isOwner}
            title={!isOwner ? "팀 소유자만 수동 생성 가능" : undefined}
          >
            {buildMutation.isPending ? (
              <>
                <Loader2 className="me-2 size-4 animate-spin" /> 생성 중…
              </>
            ) : (
              <>
                <Sparkles className="me-2 size-4" /> 지금 생성
              </>
            )}
          </Button>
        </div>
      </div>

      {buildError && (
        <div className="mb-4 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {buildError}
        </div>
      )}
      {buildSummary?.success && (
        <div className="mb-4 rounded-xl border px-4 py-3 text-sm text-muted-foreground">
          {buildSummary.articles_built}개의 아티클을 갱신했습니다.
          {buildSummary.generated_by && ` (${buildSummary.generated_by})`}
        </div>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BookOpen className="size-4" /> 아티클
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {articlesQuery.isLoading ? (
                <ArticleListSkeleton />
              ) : articles.length === 0 ? (
                <div className="rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">
                  아직 생성된 위키가 없습니다. 팀 메모리나 공용 문서를 쌓은 뒤
                  &lsquo;지금 생성&rsquo;을 눌러주세요.
                </div>
              ) : (
                grouped.map(([category, items]) => (
                  <div key={category} className="space-y-1">
                    <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {category}
                    </p>
                    <div className="space-y-1">
                      {items.map((article) => {
                        const active = selectedSlug === article.slug;
                        return (
                          <button
                            key={article.id}
                            type="button"
                            onClick={() => setSelectedSlug(article.slug)}
                            className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-accent ${
                              active ? "border-primary bg-primary/5" : "bg-background"
                            }`}
                          >
                            <p className="truncate font-medium">{article.title}</p>
                            {article.summary && (
                              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                                {article.summary}
                              </p>
                            )}
                            <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                              <span>v{article.revision}</span>
                              {article.generated_by && (
                                <Badge variant="outline" className="px-1 py-0 text-[10px]">
                                  {article.generated_by}
                                </Badge>
                              )}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </aside>

        <section>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {articleQuery.data?.title ?? (articles.length === 0 ? "위키 비어 있음" : "아티클 선택")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {articleQuery.isLoading ? (
                <div className="space-y-3">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-40 w-full" />
                </div>
              ) : articleQuery.data ? (
                <article className="prose prose-sm max-w-none whitespace-pre-wrap break-words leading-relaxed dark:prose-invert">
                  {articleQuery.data.summary && (
                    <p className="text-sm text-muted-foreground">
                      {articleQuery.data.summary}
                    </p>
                  )}
                  <div className="mt-3 text-sm">{articleContent}</div>
                  {articleQuery.data.sources?.length > 0 && (
                    <div className="mt-6 rounded-xl border bg-muted/30 p-3 text-xs text-muted-foreground">
                      <p className="mb-1 font-medium">근거 자료</p>
                      <ul className="list-inside list-disc">
                        {articleQuery.data.sources.map((s) => (
                          <li key={`${s.kind}-${s.id}`}>
                            <span className="font-mono text-[10px]">[{s.kind}]</span>{" "}
                            {s.title || s.id}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </article>
              ) : articles.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  왼쪽 안내에 따라 위키를 처음 만들어 보세요.
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  왼쪽에서 아티클을 선택하세요.
                </p>
              )}
            </CardContent>
          </Card>

          <div className="mt-3 flex justify-end">
            <Button variant="ghost" size="sm" onClick={() => router.push("/teams")}>
              팀 작업공간으로 돌아가기
            </Button>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
