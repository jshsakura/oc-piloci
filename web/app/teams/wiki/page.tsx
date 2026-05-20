"use client";

import dynamic from "next/dynamic";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import remarkGfm from "remark-gfm";
import { BookOpen, Loader2, Map as MapIcon, Pencil, RefreshCcw, Sparkles } from "lucide-react";

import AppShell from "@/components/AppShell";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { WikiMiniMap } from "@/components/WikiMiniMap";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import type {
  GraphEdge,
  GraphNode,
  TeamSummary,
  TeamWikiArticle,
  TeamWikiArticleSummary,
} from "@/lib/types";

// react-markdown pulls in remark/rehype trees; dynamic-import keeps it out of
// the initial chunk and clear of any SSR pass under static export.
const ReactMarkdown = dynamic(() => import("react-markdown"), { ssr: false });

function resolveWikilinks(markdown: string, articles: TeamWikiArticleSummary[]): string {
  // Replace [[topic]] with a same-page anchor when a matching slug exists;
  // otherwise render as italics so the intended link still reads.
  const titleMap = new Map(articles.map((a) => [a.title.toLowerCase(), a.slug]));
  return markdown.replace(/\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]/g, (_, raw, alias) => {
    const label = (alias || raw).trim();
    const slug = titleMap.get(raw.trim().toLowerCase());
    if (slug) return `[${label}](#article-${slug})`;
    return `*${label}*`;
  });
}

type Notice = { tone: "ok" | "error"; text: string } | null;

const EMPTY_TEAMS: TeamSummary[] = [];

function WikiSuspenseFallback() {
  const { t } = useTranslation();
  return (
    <AppShell title={t.teams.wiki.title}>
      <p className="text-sm text-muted-foreground">{t.teams.wiki.loading}</p>
    </AppShell>
  );
}

export default function TeamWikiPage() {
  // useSearchParams() requires a Suspense boundary under static export.
  return (
    <Suspense fallback={<WikiSuspenseFallback />}>
      <TeamWikiShell />
    </Suspense>
  );
}

function TeamWikiShell() {
  const { t } = useTranslation();
  const copy = t.teams;
  const router = useRouter();
  const searchParams = useSearchParams();

  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: api.listTeams });
  const teams = teamsQuery.data ?? EMPTY_TEAMS;

  // The team lives in the URL (?id=) so the page is static-export safe and
  // shareable — no [id] dynamic segment.
  const urlTeamId = searchParams?.get("id") ?? "";
  const selectedTeamId = urlTeamId || (teams.length > 0 ? teams[0].id : "");

  // Default the URL to the first team once teams load and none was selected.
  useEffect(() => {
    if (!urlTeamId && teams.length > 0) {
      const next = new URLSearchParams(searchParams?.toString());
      next.set("id", teams[0].id);
      router.replace(`/teams/wiki?${next.toString()}`);
    }
  }, [urlTeamId, teams, router, searchParams]);

  const setTeam = (id: string) => {
    const next = new URLSearchParams(searchParams?.toString());
    next.set("id", id);
    router.push(`/teams/wiki?${next.toString()}`);
  };

  return (
    <AppShell title={copy.wiki.title}>
      {selectedTeamId ? (
        <WikiContent
          teamId={selectedTeamId}
          teams={teams}
          onSelectTeam={setTeam}
        />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <label className="text-sm font-medium text-muted-foreground" htmlFor="team-select">
              {copy.tabs.teamSelect}
            </label>
            <select
              id="team-select"
              className="h-9 min-w-48 rounded-lg border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={selectedTeamId}
              onChange={(event) => setTeam(event.target.value)}
              disabled={teams.length === 0}
            >
              <option value="" disabled>
                {copy.tabs.teamSelectPlaceholder}
              </option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
          </div>
          <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
            {copy.tabs.noTeam}
          </div>
        </>
      )}
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// LLM 위키: Obsidian-like docs view — slim TOC + clean reading pane, with the
// context map as a secondary header toggle (floating, default hidden).
// ---------------------------------------------------------------------------

function WikiContent({
  teamId,
  teams,
  onSelectTeam,
}: {
  teamId: string;
  teams: TeamSummary[];
  onSelectTeam: (id: string) => void;
}) {
  const { t } = useTranslation();
  const copy = t.teams.wiki;
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);

  // The build is async (202): we poll the team + article list every ~8s while a
  // build is in flight and stop once last_wiki_built_at advances past the value
  // captured at build-start (or after a safety timeout).
  const [building, setBuilding] = useState(false);
  const [buildNotice, setBuildNotice] = useState<Notice>(null);
  const buildBaselineRef = useRef<string | null>(null);
  const buildDeadlineRef = useRef<number>(0);

  const teamQuery = useQuery({
    queryKey: ["team", teamId],
    queryFn: () => api.getTeam(teamId),
    enabled: Boolean(teamId),
    refetchInterval: building ? 8000 : false,
  });
  const articlesQuery = useQuery({
    queryKey: ["team-wiki-articles", teamId],
    queryFn: () => api.listTeamWikiArticles(teamId),
    enabled: Boolean(teamId),
    refetchInterval: building ? 8000 : false,
  });

  const articles = articlesQuery.data ?? [];
  const isOwner = Boolean(currentUser && teamQuery.data?.owner_id === currentUser.user_id);
  const lastBuiltAt = teamQuery.data?.last_wiki_built_at ?? null;
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  // Context map: secondary, off by default. Lives as a floating panel toggled
  // from the header — it never competes with the reading pane for layout space.
  const [showMap, setShowMap] = useState(false);
  const workspaceQuery = useQuery({
    queryKey: ["team-workspace", teamId],
    queryFn: () => api.getTeamWorkspace(teamId),
    enabled: Boolean(teamId) && showMap,
  });
  const graph = workspaceQuery.data?.graph;

  useEffect(() => {
    if (!selectedSlug && articles.length > 0) setSelectedSlug(articles[0].slug);
  }, [articles, selectedSlug]);

  // Detect build completion: stop polling when the timestamp moves, or bail out
  // after the safety window so a silently-failed build doesn't spin forever.
  useEffect(() => {
    if (!building) return;
    const moved = lastBuiltAt && lastBuiltAt !== buildBaselineRef.current;
    const timedOut = Date.now() > buildDeadlineRef.current;
    if (moved || timedOut) {
      setBuilding(false);
      if (moved) {
        queryClient.invalidateQueries({ queryKey: ["team-workspace", teamId] });
      }
    }
  }, [building, lastBuiltAt, queryClient, teamId]);

  const articleQuery = useQuery<TeamWikiArticle>({
    queryKey: ["team-wiki-article", teamId, selectedSlug],
    queryFn: () => api.getTeamWikiArticle(teamId, selectedSlug as string),
    enabled: Boolean(teamId && selectedSlug),
  });

  const buildMutation = useMutation({
    mutationFn: () => api.buildTeamWiki(teamId),
    onSuccess: (res) => {
      // 202 returns immediately. Start polling regardless of started vs.
      // already_running; both mean a build is now in flight.
      buildBaselineRef.current = teamQuery.data?.last_wiki_built_at ?? null;
      buildDeadlineRef.current = Date.now() + 5 * 60 * 1000;
      setBuilding(true);
      setBuildNotice({
        tone: "ok",
        text: res.status === "already_running" ? copy.alreadyRunning : copy.buildStarted,
      });
    },
    onError: (error: unknown) =>
      setBuildNotice({
        tone: "error",
        text: error instanceof Error ? error.message : copy.buildStarted,
      }),
  });

  const isBuilding = building || buildMutation.isPending;

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
    mutationFn: (next: boolean) => api.patchTeamSettings(teamId, { auto_wiki_enabled: next }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["team", teamId] }),
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

  const articleContent = articleQuery.data
    ? resolveWikilinks(articleQuery.data.content, articles)
    : "";

  // Sources of the open article get a highlight ring on the floating map so the
  // reader can locate them spatially.
  const highlightedIds = useMemo(
    () => (articleQuery.data?.sources ?? []).map((s) => s.id),
    [articleQuery.data],
  );

  // Wikilink anchors (#article-<slug>) jump between articles in-place rather
  // than scrolling to a missing DOM id.
  const jumpToSlug = useCallback(
    (href: string | undefined) => {
      if (!href?.startsWith("#article-")) return false;
      const slug = href.slice("#article-".length);
      if (articles.some((a) => a.slug === slug)) {
        setSelectedSlug(slug);
        return true;
      }
      return false;
    },
    [articles],
  );

  return (
    <>
      {/* Header action bar: team selector + map toggle + build/refresh/auto. */}
      <div className="mb-5 flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label={t.teams.tabs.teamSelect}
              className="h-9 min-w-44 rounded-lg border bg-background px-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={teamId}
              onChange={(event) => onSelectTeam(event.target.value)}
            >
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
            {teamQuery.data?.last_wiki_built_at && (
              <span className="text-xs text-muted-foreground">
                {copy.lastBuiltPrefix}:{" "}
                {new Date(teamQuery.data.last_wiki_built_at).toLocaleString("ko-KR")}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{copy.intro}</p>
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
            {copy.autoBuild}
          </label>
          <Button
            variant={showMap ? "secondary" : "outline"}
            size="icon"
            title={showMap ? copy.hideMap : copy.showMap}
            aria-label={showMap ? copy.hideMap : copy.showMap}
            aria-pressed={showMap}
            onClick={() => setShowMap((v) => !v)}
          >
            <MapIcon className="size-4" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            title={copy.refresh}
            aria-label={copy.refresh}
            onClick={() => articlesQuery.refetch()}
            disabled={articlesQuery.isFetching}
          >
            <RefreshCcw className="size-4" />
          </Button>
          <Button
            size="sm"
            onClick={() => buildMutation.mutate()}
            disabled={isBuilding || !isOwner}
            title={!isOwner ? copy.ownerOnlyBuild : undefined}
          >
            {isBuilding ? (
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

      {isBuilding && (
        <div className="mb-4 overflow-hidden rounded-xl border bg-card">
          <div className="flex items-center gap-3 px-4 py-3">
            <span className="relative flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
              <span className="absolute inset-0 animate-ping rounded-full bg-primary/20" />
              <Sparkles className="size-4 animate-pulse text-primary" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium">{copy.buildingTitle}</p>
              <p className="text-xs text-muted-foreground">{copy.buildingQueue}</p>
            </div>
          </div>
          <div className="h-1 w-full overflow-hidden bg-primary/10">
            <div className="h-full w-1/3 animate-pulse bg-gradient-to-r from-transparent via-primary to-transparent" />
          </div>
        </div>
      )}
      {buildNotice && !isBuilding && (
        <div
          className={`mb-4 rounded-xl border px-4 py-3 text-sm ${
            buildNotice.tone === "error"
              ? "border-destructive/40 bg-destructive/10 text-destructive"
              : "bg-card text-muted-foreground"
          }`}
        >
          {buildNotice.text}
        </div>
      )}

      {/* Two-pane docs surface: slim TOC + reading pane share one opaque card,
          split by a divider, filling the viewport height. */}
      <div className="flex min-h-[60vh] flex-col overflow-hidden rounded-xl border bg-card lg:flex-row">
        <aside className="border-b p-4 lg:w-[260px] lg:shrink-0 lg:border-b-0 lg:border-e xl:w-[280px]">
          <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <BookOpen className="size-3.5" /> {copy.articles}
          </p>
          {articlesQuery.isLoading ? (
            <div className="space-y-1.5">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-7 rounded-md" />
              ))}
            </div>
          ) : articles.length === 0 ? (
            <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              {copy.emptyListHint}
            </p>
          ) : (
            <nav className="space-y-4">
              {grouped.map(([category, items]) => (
                <div key={category}>
                  <p className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                    {category}
                  </p>
                  <ul className="space-y-0.5">
                    {items.map((article) => {
                      const active = selectedSlug === article.slug;
                      return (
                        <li key={article.id}>
                          <button
                            type="button"
                            onClick={() => setSelectedSlug(article.slug)}
                            aria-current={active ? "page" : undefined}
                            className={`group flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                              active
                                ? "bg-accent font-medium text-accent-foreground"
                                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                            }`}
                          >
                            <span
                              className={`h-3.5 w-0.5 shrink-0 rounded-full ${
                                active ? "bg-primary" : "bg-transparent"
                              }`}
                              aria-hidden
                            />
                            <span className="truncate">{article.title}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
            </nav>
          )}
        </aside>

        <section className="min-w-0 flex-1 p-5 sm:p-6">
          {articleQuery.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-7 w-2/3" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-48 w-full" />
            </div>
          ) : articleQuery.data ? (
            <article className="min-w-0">
              <header className="mb-5 flex items-start justify-between gap-4 border-b pb-4">
                <div className="min-w-0 space-y-1.5">
                  <h1 className="break-words text-2xl font-bold leading-tight tracking-tight">
                    {articleQuery.data.title}
                  </h1>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>v{articleQuery.data.revision}</span>
                    {articleQuery.data.generated_by && (
                      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                        {articleQuery.data.generated_by}
                      </Badge>
                    )}
                  </div>
                  {articleQuery.data.summary && (
                    <p className="pt-1 text-sm text-muted-foreground">
                      {articleQuery.data.summary}
                    </p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  title={copy.edit}
                  aria-label={copy.edit}
                  onClick={openEdit}
                  className="shrink-0"
                >
                  <Pencil className="size-4" />
                </Button>
              </header>

              <div className="pi-prose prose prose-sm max-w-none break-words dark:prose-invert">
                {articleContent.trim() ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ href, children, ...rest }) => {
                        if (href?.startsWith("#article-")) {
                          return (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.preventDefault();
                                jumpToSlug(href);
                              }}
                              className="text-primary underline-offset-2 hover:underline"
                            >
                              {children}
                            </button>
                          );
                        }
                        return (
                          <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
                            {children}
                          </a>
                        );
                      },
                    }}
                  >
                    {articleContent}
                  </ReactMarkdown>
                ) : (
                  <p className="text-sm text-muted-foreground">{copy.selectArticlePrompt}</p>
                )}
              </div>

              {articleQuery.data.sources?.length > 0 && (
                <div className="mt-8 rounded-xl border bg-muted/30 p-3 text-xs text-muted-foreground">
                  <p className="mb-1 font-medium">{copy.sources}</p>
                  <ul className="list-inside list-disc">
                    {articleQuery.data.sources.map((s) => (
                      <li key={`${s.kind}-${s.id}`}>
                        <span className="font-mono text-[10px]">[{s.kind}]</span> {s.title || s.id}
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
                <h2 className="text-lg font-semibold sm:text-xl">{copy.emptyHeadline}</h2>
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
                  <p className="mt-1 text-xs text-muted-foreground">{copy.step1Body}</p>
                </div>
                <div className="rounded-xl border bg-card/50 p-4 text-left">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {copy.step2Label}
                  </p>
                  <p className="mt-1 text-sm font-medium">{copy.step2Title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{copy.step2Body}</p>
                </div>
                <div className="rounded-xl border bg-card/50 p-4 text-left">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {copy.step3Label}
                  </p>
                  <p className="mt-1 text-sm font-medium">{copy.step3Title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{copy.step3Body}</p>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  size="lg"
                  onClick={() => buildMutation.mutate()}
                  disabled={isBuilding || !isOwner}
                >
                  {isBuilding ? (
                    <>
                      <Loader2 className="me-2 size-4 animate-spin" /> {copy.building}
                    </>
                  ) : (
                    <>
                      <Sparkles className="me-2 size-4" /> {copy.buildNowLarge}
                    </>
                  )}
                </Button>
              </div>
              {!isOwner && <p className="text-xs text-muted-foreground">{copy.ownerOnlyHint}</p>}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 px-4 py-12 text-center text-muted-foreground">
              <BookOpen className="size-8" />
              <p className="text-sm">{copy.selectArticlePrompt}</p>
            </div>
          )}
        </section>
      </div>

      {/* Secondary context map: floating, non-inline, owned by the header toggle. */}
      {showMap && graph && (graph.nodes as GraphNode[]).length > 0 && (
        <WikiMiniMap
          nodes={graph.nodes as GraphNode[]}
          edges={graph.edges as GraphEdge[]}
          highlightedIds={highlightedIds}
          hidden={false}
          onHiddenChange={(h) => setShowMap(!h)}
          onNodeClick={(node) => {
            const lower = node.label.toLowerCase();
            const match = articles.find((a) => a.title.toLowerCase() === lower);
            if (match) setSelectedSlug(match.slug);
          }}
        />
      )}

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
            <p className="text-[11px] text-muted-foreground">{copy.editNotice}</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
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
    </>
  );
}
