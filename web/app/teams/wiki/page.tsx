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
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
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

function WikiSuspenseFallback() {
  const { t } = useTranslation();
  return (
    <AppShell title={t.teams.wiki.title}>
      <p className="text-sm text-muted-foreground">{t.teams.wiki.loading}</p>
    </AppShell>
  );
}

export default function TeamWikiPage() {
  // useSearchParams() requires Suspense at static-export time. The shell does
  // the data-fetching itself so the fallback can be a thin skeleton.
  return (
    <Suspense fallback={<WikiSuspenseFallback />}>
      <TeamWikiContent />
    </Suspense>
  );
}

function TeamWikiContent() {
  const { t } = useTranslation();
  const copy = t.teams.wiki;
  const currentUser = useAuthStore((s) => s.user);
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

  // Reached via the sidebar with no ?id — fall back to the first team so the
  // page is actually usable instead of showing an empty, disabled shell.
  useEffect(() => {
    if (!teamId && (teamsQuery.data?.length ?? 0) > 0) {
      router.replace(`/teams/wiki?id=${teamsQuery.data![0].id}`);
    }
  }, [teamId, teamsQuery.data, router]);

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
      const key = article.category || copy.otherCategory;
      const arr = buckets.get(key) ?? [];
      arr.push(article);
      buckets.set(key, arr);
    }
    return Array.from(buckets.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [articles, copy.otherCategory]);

  // Owner = the logged-in user owns this team. (The old check compared the
  // owner to itself among members, so it never reflected the viewer — leaving
  // the auto-build toggle / 지금 생성 disabled even for the actual owner.)
  const isOwner = Boolean(currentUser && teamQuery.data?.owner_id === currentUser.user_id);

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
    <AppShell title={teamQuery.data?.name ? `${teamQuery.data.name} · ${copy.titleSuffix}` : copy.title}>
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
            {copy.intro}
          </p>
          {teamQuery.data?.last_wiki_built_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              {copy.lastBuiltPrefix}: {new Date(teamQuery.data.last_wiki_built_at).toLocaleString("ko-KR")}
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
            title={copy.teamSelect}
          >
            <option value="" disabled>
              {copy.teamSelectPlaceholder}
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
            {copy.autoBuild}
          </label>
          {workspaceQuery.data?.graph && (
            <Button
              variant={mapHidden ? "outline" : "secondary"}
              size="sm"
              className="hidden sm:inline-flex"
              onClick={() => setMapHidden((v) => !v)}
            >
              <MapIcon className="me-2 size-4" />
              {mapHidden ? copy.showMap : copy.hideMap}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => articlesQuery.refetch()}
            disabled={articlesQuery.isFetching}
          >
            <RefreshCcw className="me-2 size-4" /> {copy.refresh}
          </Button>
          <Button
            size="sm"
            onClick={() => buildMutation.mutate()}
            disabled={buildMutation.isPending || !isOwner}
            title={!isOwner ? copy.ownerOnlyBuild : undefined}
          >
            {buildMutation.isPending ? (
              <>
                <Loader2 className="me-2 size-4 animate-spin" /> {copy.building}
              </>
            ) : (
              <>
                <Sparkles className="me-2 size-4" /> {copy.buildNow}
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
          {buildSummary.articles_built}
          {copy.builtCountSuffix}
          {buildSummary.generated_by && ` (${buildSummary.generated_by})`}
        </div>
      )}

      <div className="grid items-stretch gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="flex flex-col gap-4">
          <Card className="flex-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BookOpen className="size-4" /> {copy.articles}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {articlesQuery.isLoading ? (
                <ArticleListSkeleton />
              ) : articles.length === 0 ? (
                <div className="rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">
                  {copy.emptyListHint}
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
              <div className="border-t pt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => router.push("/teams")}
                >
                  {copy.backToTeam}
                </Button>
              </div>
            </CardContent>
          </Card>
        </aside>

        <section className="flex flex-col">
          <Card className="flex-1">
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle className="min-w-0 truncate text-base">
                {articleQuery.data?.title ?? (articles.length === 0 ? copy.wikiEmptyTitle : copy.selectArticleTitle)}
              </CardTitle>
              {articleQuery.data && (
                <Button variant="outline" size="sm" onClick={openEdit}>
                  <Pencil className="me-2 size-4" /> {copy.edit}
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
                      <p className="mb-1 font-medium">{copy.sources}</p>
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
                      {copy.emptyHeadline}
                    </h2>
                    <p className="mx-auto max-w-md text-sm text-muted-foreground sm:text-[15px]">
                      {copy.emptyBody}
                    </p>
                  </div>

                  <div className="mt-2 grid w-full max-w-xl gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border bg-card/50 p-4 text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {copy.step1Label}
                      </p>
                      <p className="mt-1 text-sm font-medium">{copy.step1Title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {copy.step1Body}
                      </p>
                    </div>
                    <div className="rounded-xl border bg-card/50 p-4 text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {copy.step2Label}
                      </p>
                      <p className="mt-1 text-sm font-medium">{copy.step2Title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {copy.step2Body}
                      </p>
                    </div>
                    <div className="rounded-xl border bg-card/50 p-4 text-left">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {copy.step3Label}
                      </p>
                      <p className="mt-1 text-sm font-medium">{copy.step3Title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {copy.step3Body}
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
                          <Loader2 className="me-2 size-4 animate-spin" /> {copy.building}
                        </>
                      ) : (
                        <>
                          <Sparkles className="me-2 size-4" /> {copy.buildNowLarge}
                        </>
                      )}
                    </Button>
                    <Button variant="outline" size="lg" onClick={() => router.push("/teams")}>
                      {copy.goUpload}
                    </Button>
                  </div>
                  {!isOwner && (
                    <p className="text-xs text-muted-foreground">
                      {copy.ownerOnlyHint}
                    </p>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3 px-4 py-12 text-center text-muted-foreground">
                  <BookOpen className="size-8" />
                  <p className="text-sm">{copy.selectArticlePrompt}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      </div>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{copy.editArticle}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="wiki-title">
                {copy.titleField}
              </label>
              <Input
                id="wiki-title"
                value={draftTitle}
                onChange={(e) => setDraftTitle(e.target.value)}
                placeholder={copy.titlePlaceholder}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground" htmlFor="wiki-summary">
                {copy.summaryField}
              </label>
              <Input
                id="wiki-summary"
                value={draftSummary}
                onChange={(e) => setDraftSummary(e.target.value)}
                placeholder={copy.summaryPlaceholder}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">{copy.bodyField}</label>
              <MarkdownEditor
                value={draftContent}
                onChange={setDraftContent}
                height={420}
                imageUploadUrl={`/api/teams/${teamId}/wiki/images`}
              />
            </div>
            <p className="text-[11px] text-muted-foreground">
              {copy.editNotice}
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditOpen(false)}>
              {copy.cancel}
            </Button>
            <Button onClick={() => editMutation.mutate()} disabled={editMutation.isPending}>
              {editMutation.isPending ? (
                <>
                  <Loader2 className="me-2 size-4 animate-spin" /> {copy.saving}
                </>
              ) : (
                copy.save
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
                <Badge variant="secondary">{t.teams.nodeKinds[activeNode.kind] ?? activeNode.kind}</Badge>
                {activeNode.version != null && (
                  <span className="text-xs text-muted-foreground">v{activeNode.version}</span>
                )}
              </div>
              {activeNode.path && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">{copy.nodePathLabel}</p>
                  <p className="break-all font-mono text-xs">{activeNode.path}</p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setActiveNode(null)}>
              {copy.close}
            </Button>
            {activeNodeArticle && (
              <Button
                onClick={() => {
                  setSelectedSlug(activeNodeArticle.slug);
                  setActiveNode(null);
                }}
              >
                <BookOpen className="me-2 size-4" /> {copy.openInWiki}
              </Button>
            )}
            {(activeNode?.kind === "doc" || activeNode?.kind === "note") &&
              activeNode.download_url &&
              (nodeViewable(activeNode) ? (
                <Button asChild>
                  <a href={activeNode.download_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="me-2 size-4" /> {copy.open}
                  </a>
                </Button>
              ) : (
                <Button asChild>
                  <a href={activeNode.download_url} target="_blank" rel="noreferrer">
                    <Download className="me-2 size-4" /> {copy.download}
                  </a>
                </Button>
              ))}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
