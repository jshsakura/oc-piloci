"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Download,
  ExternalLink,
  Loader2,
  Map as MapIcon,
  Pencil,
  RefreshCcw,
  Sparkles,
} from "lucide-react";

import AppShell from "@/components/AppShell";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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

const NODE_KIND_LABEL: Record<GraphNode["kind"], string> = {
  project: "프로젝트",
  note: "메모",
  tag: "태그",
  topic: "토픽",
  team: "팀",
  folder: "폴더",
  doc: "문서",
};

const _VIEWABLE_EXT = new Set([
  "md", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml",
  "csv", "html", "css", "sql", "sh", "rst", "ini", "cfg", "log", "pdf",
  "png", "jpg", "jpeg", "gif", "webp", "svg",
]);

// A node's file is browser-viewable when its path extension renders inline;
// otherwise the popup offers a download instead of an "open".
function nodeViewable(node: GraphNode): boolean {
  const path = node.path ?? node.label ?? "";
  const dot = path.lastIndexOf(".");
  return dot >= 0 && _VIEWABLE_EXT.has(path.slice(dot + 1).toLowerCase());
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
  // Map visibility is owned here so the header action bar can toggle it.
  const [mapHidden, setMapHidden] = useState(false);
  // Clicking a map node opens this info popup instead of navigating/downloading.
  const [activeNode, setActiveNode] = useState<GraphNode | null>(null);

  const teamsQuery = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

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

  // Edit modal state — when open, we hold a local copy of the article so the
  // editor is controlled and we can compare on save to know if anything moved.
  const [editOpen, setEditOpen] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftSummary, setDraftSummary] = useState("");
  const [draftContent, setDraftContent] = useState("");

  const openEdit = () => {
    if (!articleQuery.data) return;
    setDraftTitle(articleQuery.data.title ?? "");
    setDraftSummary(articleQuery.data.summary ?? "");
    setDraftContent(articleQuery.data.content ?? "");
    setEditOpen(true);
  };

  const editMutation = useMutation({
    mutationFn: () =>
      api.updateTeamWikiArticle(teamId, selectedSlug as string, {
        title: draftTitle,
        summary: draftSummary || null,
        content: draftContent,
      }),
    onSuccess: () => {
      setEditOpen(false);
      queryClient.invalidateQueries({ queryKey: ["team-wiki-article", teamId, selectedSlug] });
      queryClient.invalidateQueries({ queryKey: ["team-wiki-articles", teamId] });
      queryClient.invalidateQueries({ queryKey: ["team-workspace", teamId] });
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

  // Click on a graph node opens an info popup — never auto-navigate or
  // download. The popup offers explicit actions (위키에서 열기 / 다운로드).
  const handleNodeClick = (node: GraphNode) => {
    setActiveNode(node);
  };

  // Article that an active node maps to by title, if any — drives the
  // "위키에서 열기" action in the popup.
  const activeNodeArticle = useMemo(() => {
    if (!activeNode) return null;
    const lower = activeNode.label.toLowerCase();
    return articles.find((a) => a.title.toLowerCase() === lower) ?? null;
  }, [activeNode, articles]);

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
          hidden={mapHidden}
          onHiddenChange={setMapHidden}
        />
      )}
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            팀이 쌓아둔 메모와 문서를 AI가 한국어 위키 아티클로 정리합니다.
          </p>
          {teamQuery.data?.last_wiki_built_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              마지막 생성: {new Date(teamQuery.data.last_wiki_built_at).toLocaleString("ko-KR")}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="h-9 rounded-lg border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={teamId}
            onChange={(event) => {
              const next = event.target.value;
              if (next) router.push(`/teams/wiki?id=${next}`);
            }}
            title="팀 선택"
          >
            <option value="" disabled>
              팀 선택…
            </option>
            {(teamsQuery.data ?? []).map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
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
          {workspaceQuery.data?.graph && (
            <Button
              variant={mapHidden ? "outline" : "secondary"}
              size="sm"
              className="hidden sm:inline-flex"
              onClick={() => setMapHidden((v) => !v)}
            >
              <MapIcon className="me-2 size-4" />
              {mapHidden ? "맥락지도 보기" : "맥락지도 숨기기"}
            </Button>
          )}
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

      <div className="grid items-stretch gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="flex flex-col gap-4">
          <Card className="flex-1">
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

        <section className="flex flex-col">
          <Card className="flex-1">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle className="min-w-0 truncate text-base">
                {articleQuery.data?.title ?? (articles.length === 0 ? "위키 비어 있음" : "아티클 선택")}
              </CardTitle>
              {articleQuery.data && (
                <Button variant="outline" size="sm" onClick={openEdit}>
                  <Pencil className="me-2 size-4" /> 편집
                </Button>
              )}
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
                <div className="flex flex-col items-center gap-6 px-4 py-12 text-center sm:py-20">
                  <div className="flex size-16 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/15">
                    <BookOpen className="size-7 text-primary" />
                  </div>
                  <div className="space-y-2">
                    <h2 className="text-lg font-semibold sm:text-xl">
                      아직 정리된 위키가 없어요
                    </h2>
                    <p className="mx-auto max-w-md text-sm text-muted-foreground sm:text-[15px]">
                      팀이 올린 문서와 메모를 AI가 한국어 아티클로 묶어줍니다.
                      자료를 한 번이라도 쌓아두면 새벽에 자동으로 한 번 정리하고,
                      바로 보고 싶다면 아래 버튼으로 즉시 만들 수 있어요.
                    </p>
                  </div>

                  <div className="mt-2 grid w-full max-w-xl gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border bg-card/50 p-4 text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        1단계
                      </p>
                      <p className="mt-1 text-sm font-medium">공용 문서 올리기</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        팀 페이지에서 폴더 구조 그대로 업로드.
                      </p>
                    </div>
                    <div className="rounded-xl border bg-card/50 p-4 text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        2단계
                      </p>
                      <p className="mt-1 text-sm font-medium">팀 메모 쌓기</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        결정·회의록·일화. `memory` 툴로 한 줄씩.
                      </p>
                    </div>
                    <div className="rounded-xl border bg-card/50 p-4 text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        3단계
                      </p>
                      <p className="mt-1 text-sm font-medium">AI 위키 만들기</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        새벽 자동 + 지금 생성 버튼.
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center justify-center gap-2">
                    <Button
                      size="lg"
                      onClick={() => buildMutation.mutate()}
                      disabled={buildMutation.isPending || !isOwner}
                    >
                      {buildMutation.isPending ? (
                        <>
                          <Loader2 className="me-2 size-4 animate-spin" /> 생성 중…
                        </>
                      ) : (
                        <>
                          <Sparkles className="me-2 size-4" /> 지금 위키 만들기
                        </>
                      )}
                    </Button>
                    <Button variant="outline" size="lg" onClick={() => router.push("/teams")}>
                      문서 업로드하러 가기
                    </Button>
                  </div>
                  {!isOwner && (
                    <p className="text-xs text-muted-foreground">
                      팀 소유자만 수동 생성을 누를 수 있어요. 새벽 자동 빌드는 켜면 누구나 받아요.
                    </p>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3 px-4 py-12 text-center text-muted-foreground">
                  <BookOpen className="size-8" />
                  <p className="text-sm">왼쪽에서 아티클을 선택하세요.</p>
                </div>
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

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>아티클 편집</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="wiki-title">
                제목
              </label>
              <Input
                id="wiki-title"
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder="아티클 제목"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="wiki-summary">
                요약 (1~2문장)
              </label>
              <Input
                id="wiki-summary"
                value={draftSummary}
                onChange={(e) => setDraftSummary(e.target.value)}
                placeholder="짧은 요약"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">본문 (마크다운)</label>
              <MarkdownEditor
                value={draftContent}
                onChange={setDraftContent}
                height={420}
                imageUploadUrl={`/api/teams/${teamId}/wiki/images`}
              />
            </div>
            <p className="text-[11px] text-muted-foreground">
              사람이 고친 결은 다음 새벽 위키 빌드의 스타일 힌트로 자동 반영됩니다.
              revision 히스토리에 이전 본문이 자동 저장돼요.
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditOpen(false)}>
              취소
            </Button>
            <Button onClick={() => editMutation.mutate()} disabled={editMutation.isPending}>
              {editMutation.isPending ? (
                <>
                  <Loader2 className="me-2 size-4 animate-spin" /> 저장 중…
                </>
              ) : (
                "저장"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(activeNode)} onOpenChange={(open) => !open && setActiveNode(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="break-words">{activeNode?.label}</DialogTitle>
          </DialogHeader>
          {activeNode && (
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{NODE_KIND_LABEL[activeNode.kind] ?? activeNode.kind}</Badge>
                {activeNode.version != null && (
                  <span className="text-xs text-muted-foreground">v{activeNode.version}</span>
                )}
              </div>
              {activeNode.path && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">경로</p>
                  <p className="break-all font-mono text-xs">{activeNode.path}</p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setActiveNode(null)}>
              닫기
            </Button>
            {activeNodeArticle && (
              <Button
                onClick={() => {
                  setSelectedSlug(activeNodeArticle.slug);
                  setActiveNode(null);
                }}
              >
                <BookOpen className="me-2 size-4" /> 위키에서 열기
              </Button>
            )}
            {(activeNode?.kind === "doc" || activeNode?.kind === "note") &&
              activeNode.download_url &&
              (nodeViewable(activeNode) ? (
                <Button asChild>
                  <a href={activeNode.download_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="me-2 size-4" /> 열기
                  </a>
                </Button>
              ) : (
                <Button asChild>
                  <a href={activeNode.download_url} target="_blank" rel="noreferrer">
                    <Download className="me-2 size-4" /> 다운로드
                  </a>
                </Button>
              ))}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
