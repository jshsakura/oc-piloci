"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FolderKanban, Search } from "lucide-react";
import AppShell from "@/components/AppShell";
import { MemoryGraphPanel } from "@/components/MemoryGraphPanel";
import { VaultNoteDetail } from "@/components/VaultNoteDetail";
import RoutePending from "@/components/RoutePending";
import { Button } from "@/components/ui/button";
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

  // Auto-select the first note ONCE per slug. Tracking by slug (not by
  // mount) matters: without the ref, the effect refired whenever noteId
  // became empty — e.g. when the mobile "목록으로" button cleared it — so
  // back-to-list immediately bounced into the just-cleared note, making
  // the button look dead. We arm auto-select per project and disarm it as
  // soon as either a note is selected or the user explicitly deselects.
  const autoSelectedSlugRef = useRef<string | null>(null);
  useEffect(() => {
    if (!slug || !workspaceQuery.data) return;
    if (autoSelectedSlugRef.current === slug) return;
    if (noteId) {
      autoSelectedSlugRef.current = slug;
      return;
    }
    if (notes.length === 0) return;
    autoSelectedSlugRef.current = slug;
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

  // v0.3.59: just a single project selector at the top of the page.
  // Always visible — switches between projects regardless of slug state.
  const handleSelectProject = (nextSlug: string) => {
    pushParams(router, searchParams, { slug: nextSlug, note: null });
  };

  return (
    <AppShell title={copy.title}>
      <div className="mb-4 flex items-center gap-2">
        <FolderKanban className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <Select value={slug ?? ""} onValueChange={handleSelectProject}>
          <SelectTrigger className="h-9 w-64">
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

      {!slug && (
        <div className="bg-card text-muted-foreground rounded-md px-6 py-10 text-center text-sm">
          {copy.pickProjectHint}
        </div>
      )}

      {slug && (
        // v0.3.63 layout: ONE workspace card divided by internal borders,
        // not two stacked cards with a gap. The graph is the top section,
        // list+detail share the bottom — both sized per breakpoint so the
        // page isn't crushed on mobile nor barren on desktop.
        <div className="bg-card overflow-hidden rounded-lg border">
          {/* Graph section — flex column so GraphPane's flex-1 states fill
              and center; relative so the loading skeleton can absolutely
              cover the area without doing card-in-card chrome. */}
          <div className="relative flex h-[260px] flex-col overflow-hidden border-b sm:h-[380px] lg:h-[440px]">
            {workspaceQuery.isLoading ? (
              <div className="bg-muted/40 absolute inset-0 animate-pulse" />
            ) : (
              <GraphPane
                isLoading={false}
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
                  selectedNodeId={noteId}
                />
              </GraphPane>
            )}
          </div>

          {/* List + Detail — single grid row. md-only divider between the
              panes; mobile shows one pane at a time and toggles via the
              "목록으로" button in the detail header. */}
          <div className="grid h-[460px] items-stretch overflow-hidden md:h-[520px] md:grid-cols-[260px_minmax(0,1fr)]">
            {(
              <div
                className={cn(
                  "flex h-full min-h-0 flex-col overflow-hidden p-3 md:border-e",
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
                  {workspaceQuery.isLoading ? (
                    <li className="space-y-1.5 px-1 py-1">
                      {Array.from({ length: 6 }).map((_, i) => (
                        <div key={i} className="bg-muted/40 h-9 animate-pulse rounded" />
                      ))}
                    </li>
                  ) : filteredNotes.length === 0 ? (
                    <li className="text-muted-foreground px-2 py-4 text-center text-xs">
                      {copy.empty}
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
              </div>
            )}

            {/* Detail pane — selected note body + backlinks. Lives
                inside the same outer card as the list. */}
            <div
              className={cn(
                "flex h-full min-h-0 flex-col overflow-hidden p-4",
                !selectedNote && "hidden md:flex",
              )}
            >
            {workspaceQuery.isLoading ? (
              <div className="space-y-3">
                <div className="bg-muted/40 h-5 w-3/4 animate-pulse rounded" />
                <div className="bg-muted/40 h-3 w-full animate-pulse rounded" />
                <div className="bg-muted/40 h-3 w-5/6 animate-pulse rounded" />
                <div className="bg-muted/40 h-3 w-2/3 animate-pulse rounded" />
              </div>
            ) : selectedNote ? (
              <>
                <div className="mb-3 flex items-center gap-2 md:hidden">
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
          </div>
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
