"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FolderKanban, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import AppShell from "@/components/AppShell";
import { MemoryGraphPanel } from "@/components/MemoryGraphPanel";
import { VaultNoteDetail } from "@/components/VaultNoteDetail";
import RoutePending from "@/components/RoutePending";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { GraphNode, VaultNote } from "@/lib/types";

/**
 * /memory — the Obsidian-style wiki entry. Three-pane layout on desktop:
 *   left:   note list + search
 *   center: memory graph (click a node to focus the right pane)
 *   right:  selected memory's full body + outbound links ("백링크")
 *
 * Project is chosen via the top selector and persisted in ?slug=. Note id
 * persists in ?note=, so back-button navigation between notes is real
 * history rather than in-memory state. Mobile collapses the layout to one
 * pane at a time (list → detail → back).
 */
function WikiContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();
  const copy = t.memoryWiki;

  const slug = searchParams.get("slug");
  const noteId = searchParams.get("note");
  const [query, setQuery] = useState("");
  // Collapsible left list — gives the graph/detail panes the full row
  // when toggled off. Default open so newcomers see the list first.
  const [listOpen, setListOpen] = useState(true);

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) router.replace("/login");
  }, [hasHydrated, isBootstrapping, router, user]);

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    enabled: !!user,
  });

  const workspaceQuery = useQuery({
    queryKey: ["project-workspace", slug],
    queryFn: () => api.projectWorkspace(slug as string),
    enabled: Boolean(slug),
  });

  const projects = projectsQuery.data ?? [];
  const notes = useMemo(
    () => workspaceQuery.data?.workspace.notes ?? [],
    [workspaceQuery.data?.workspace.notes],
  );
  // Stable graph references — MemoryGraphPanel restarts the d3 sim on any
  // identity change, so memoising avoids visual flicker every refetch tick.
  const graphNodes = useMemo(
    () => workspaceQuery.data?.workspace.graph.nodes ?? [],
    [workspaceQuery.data?.workspace.graph.nodes],
  );
  const graphEdges = useMemo(
    () => workspaceQuery.data?.workspace.graph.edges ?? [],
    [workspaceQuery.data?.workspace.graph.edges],
  );

  const filteredNotes = useMemo(() => {
    if (!query.trim()) return notes;
    const q = query.toLowerCase();
    return notes.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        n.excerpt.toLowerCase().includes(q) ||
        n.tags.some((tag) => tag.toLowerCase().includes(q)),
    );
  }, [notes, query]);

  // Auto-select the first note on first load so the detail pane is never
  // empty when the user lands fresh — but respect an explicit ?note= so
  // deep links stay sticky.
  useEffect(() => {
    if (!slug || !workspaceQuery.data) return;
    if (noteId) return;
    if (notes.length === 0) return;
    pushParams(router, searchParams, { slug, note: notes[0].memory_id });
  }, [slug, noteId, notes, workspaceQuery.data, router, searchParams]);

  const selectedNote: VaultNote | null =
    notes.find((n) => n.memory_id === noteId) ?? null;

  // VaultNote.links contains the outbound link slugs that the curator
  // extracted. We match them back to in-project notes for jump-able
  // backlinks; unmatched links surface as plain text.
  const linkedNotes = useMemo(() => {
    if (!selectedNote) return [];
    return selectedNote.links
      .map((lk) => {
        const target = notes.find(
          (n) => n.path === lk || n.title === lk || n.memory_id === lk,
        );
        return { label: lk, note: target };
      })
      .slice(0, 12);
  }, [selectedNote, notes]);

  function handleSelectProject(nextSlug: string) {
    pushParams(router, searchParams, { slug: nextSlug, note: null });
  }

  function handleSelectNote(nextNoteId: string) {
    if (!slug) return;
    pushParams(router, searchParams, { slug, note: nextNoteId });
  }

  function handleGraphNode(node: GraphNode) {
    // Graph node ids match memory_id for "note" kinds; the curator emits
    // synthetic "tag"/"topic" nodes that have no direct memory — ignore
    // those clicks rather than jumping into a 404 state.
    if (node.kind === "note") handleSelectNote(node.id);
  }

  if (!hasHydrated || isBootstrapping) {
    return (
      <AppShell>
        <RoutePending title={copy.pending.title} description={copy.pending.desc} />
      </AppShell>
    );
  }
  if (!user) {
    return (
      <RoutePending
        fullScreen
        title={copy.pending.title}
        description={copy.pending.desc}
      />
    );
  }

  // v0.3.50 header: replaced the heavyweight PageHero with a single
  // sticky topbar row aligned to the sidebar's 14px brand band. Title +
  // project selector + list toggle all live in one line so the page
  // doesn't feel "card-on-card-on-card" anymore.
  return (
    <AppShell>
      <div className="bg-background/80 -mx-4 -mt-6 mb-4 flex h-12 items-center gap-3 border-b px-4 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex min-w-0 items-baseline gap-2">
          <h1 className="text-base font-semibold tracking-tight">{copy.title}</h1>
          <p className="text-muted-foreground hidden truncate text-xs sm:block">
            {copy.subtitle}
          </p>
        </div>
        <div className="ms-auto flex items-center gap-2">
          {slug && (
            <Button
              variant="ghost"
              size="sm"
              className="hidden md:inline-flex"
              onClick={() => setListOpen((v) => !v)}
              aria-label={listOpen ? copy.collapseList : copy.expandList}
            >
              {listOpen ? (
                <PanelLeftClose className="size-4" />
              ) : (
                <PanelLeftOpen className="size-4" />
              )}
            </Button>
          )}
          <Select value={slug ?? ""} onValueChange={handleSelectProject}>
            <SelectTrigger className="h-8 w-44 text-xs sm:w-56 sm:text-sm">
              <FolderKanban className="text-muted-foreground me-1.5 size-3.5" aria-hidden />
              <SelectValue placeholder={copy.selectProject} />
            </SelectTrigger>
            <SelectContent>
              {projects.map((p) => (
                <SelectItem key={p.id} value={p.slug}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {!slug && (
        <Card className="mt-6 px-6 py-10 text-center text-sm text-muted-foreground">
          {copy.pickProjectHint}
        </Card>
      )}

      {slug && (
        // Outer grid: graph on top (~55%), list+detail row below (~45%).
        // Heights are explicit dvh anchors so the two rows always sum to
        // the visible viewport minus the header/hero.
        // Available height = dvh − (sticky app header 56) − (slim wiki
        // topbar 48) − (footer ~44) − page padding. 14rem ≈ 224px keeps
        // some breathing room while letting the graph claim ~55% of the
        // remaining vertical space.
        <div className="grid h-[calc(100dvh-14rem)] grid-rows-[minmax(0,1.2fr)_minmax(0,1fr)] gap-4">
          {/* TOP — context map full width */}
          <Card className="flex min-h-0 flex-col p-3">
            <GraphPane
              isLoading={workspaceQuery.isLoading}
              error={workspaceQuery.error as Error | null}
              hasMemories={notes.length > 0}
              nodeCount={graphNodes.length}
              loadingText={copy.loading}
              emptyMemoriesText={copy.noMemories}
              noGraphText={copy.noGraph}
              errorText={copy.loadError}
            >
              <MemoryGraphPanel
                nodes={graphNodes}
                edges={graphEdges}
                onNodeClick={handleGraphNode}
              />
            </GraphPane>
          </Card>

          {/* BOTTOM ROW — list (collapsible) + detail */}
          <div
            className={cn(
              "grid min-h-0 items-stretch gap-4",
              listOpen
                ? "md:grid-cols-[240px_minmax(0,1fr)]"
                : "md:grid-cols-[minmax(0,1fr)]",
            )}
          >
            {listOpen && (
              <Card
                className={cn(
                  "flex h-full min-h-0 flex-col overflow-hidden p-3",
                  selectedNote && "hidden md:flex",
                )}
              >
                <div className="relative mb-2">
                  <Search
                    className="text-muted-foreground absolute start-2 top-1/2 size-3.5 -translate-y-1/2"
                    aria-hidden
                  />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder={copy.searchPlaceholder}
                    className="h-8 ps-7 text-sm"
                  />
                </div>
                <ul className="min-h-0 flex-1 overflow-y-auto">
                  {filteredNotes.length === 0 ? (
                    <li className="text-muted-foreground px-2 py-4 text-center text-xs">
                      {workspaceQuery.isLoading ? copy.loading : copy.empty}
                    </li>
                  ) : (
                    filteredNotes.map((n) => {
                      const active = n.memory_id === noteId;
                      return (
                        <li key={n.memory_id}>
                          <button
                            type="button"
                            onClick={() => handleSelectNote(n.memory_id)}
                            className={cn(
                              "w-full rounded-md px-2 py-1.5 text-start text-xs transition-colors",
                              active
                                ? "bg-primary/10 text-foreground"
                                : "text-muted-foreground hover:bg-muted/50",
                            )}
                          >
                            <p className="line-clamp-1 font-medium">{n.title}</p>
                            <p className="line-clamp-1 text-[10px]">{n.excerpt}</p>
                          </button>
                        </li>
                      );
                    })
                  )}
                </ul>
              </Card>
            )}

            {/* Detail pane — selected note body + backlinks */}
            <Card
              className={cn(
                "flex h-full min-h-0 flex-col overflow-hidden p-4",
                !selectedNote && "hidden md:flex",
              )}
            >
            {selectedNote ? (
              <>
                <div className="mb-3 flex items-center gap-2 lg:hidden">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="-ms-2"
                    onClick={() => handleSelectNote("")}
                  >
                    <ArrowLeft className="me-1 size-4" /> {copy.backToList}
                  </Button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  <VaultNoteDetail note={selectedNote} />
                  {linkedNotes.length > 0 && (
                    <div className="mt-6 border-t pt-4">
                      <p className="text-muted-foreground mb-2 text-xs font-medium uppercase tracking-wide">
                        {copy.backlinks}
                      </p>
                      <ul className="space-y-1">
                        {linkedNotes.map(({ label, note }, idx) => (
                          <li key={`${label}-${idx}`}>
                            {note ? (
                              <button
                                type="button"
                                onClick={() => handleSelectNote(note.memory_id)}
                                className="text-primary hover:underline text-sm"
                              >
                                {note.title}
                              </button>
                            ) : (
                              <span className="text-muted-foreground text-sm">
                                {label}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <p className="text-muted-foreground py-10 text-center text-sm">
                {copy.pickNoteHint}
              </p>
            )}
          </Card>
          </div>
        </div>
      )}
    </AppShell>
  );
}

/**
 * Wraps the memory graph with an explicit set of empty / loading / error
 * states. v0.3.47 had a single "noGraph" fallback that conflated "no data
 * yet" with "data exists but no relationships" — the user couldn't tell
 * whether something was broken or just empty.
 */
function GraphPane({
  isLoading,
  error,
  hasMemories,
  nodeCount,
  loadingText,
  emptyMemoriesText,
  noGraphText,
  errorText,
  children,
}: {
  isLoading: boolean;
  error: Error | null;
  hasMemories: boolean;
  nodeCount: number;
  loadingText: string;
  emptyMemoriesText: string;
  noGraphText: string;
  errorText: string;
  children: React.ReactNode;
}) {
  if (isLoading) {
    return (
      <div className="text-muted-foreground flex flex-1 items-center justify-center text-sm">
        {loadingText}
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-destructive flex flex-1 items-center justify-center text-sm">
        {errorText}
      </div>
    );
  }
  if (!hasMemories) {
    return (
      <div className="text-muted-foreground flex flex-1 items-center justify-center text-center text-sm">
        <p className="max-w-xs px-4">{emptyMemoriesText}</p>
      </div>
    );
  }
  if (nodeCount === 0) {
    return (
      <div className="text-muted-foreground flex flex-1 items-center justify-center text-center text-sm">
        <p className="max-w-xs px-4">{noGraphText}</p>
      </div>
    );
  }
  return <div className="min-h-0 flex-1">{children}</div>;
}

function pushParams(
  router: ReturnType<typeof useRouter>,
  current: URLSearchParams,
  updates: Record<string, string | null>,
) {
  const params = new URLSearchParams(current.toString());
  for (const [k, v] of Object.entries(updates)) {
    if (v === null || v === "") params.delete(k);
    else params.set(k, v);
  }
  const qs = params.toString();
  router.replace(qs ? `/memory?${qs}` : "/memory");
}

export default function MemoryWikiPage() {
  return (
    <Suspense fallback={null}>
      <WikiContent />
    </Suspense>
  );
}
