"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FolderKanban, Search } from "lucide-react";
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

  // Memory wiki gets a slim hero (title + project selector inline) so the
  // 3-pane layout below can claim as much vertical room as possible.
  // Page is intentionally full-bleed — AppShell's `main` stopped capping
  // width in v0.3.47, so the wiki can spread to the screen edge minus
  // the sidebar.
  return (
    <AppShell>
      <div className="flex flex-col gap-2 border-b pb-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
            {copy.eyebrow}
          </p>
          <h1 className="text-lg font-semibold tracking-tight sm:text-xl">{copy.title}</h1>
        </div>
        <div className="flex items-center gap-2">
          <FolderKanban className="text-muted-foreground size-4" aria-hidden />
          <Select value={slug ?? ""} onValueChange={handleSelectProject}>
            <SelectTrigger className="w-56">
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
        // Re-balanced from [260, 1fr, 320] → [220, 1.4fr, 1.6fr] so the
        // detail pane (right) gets meaningful room for body + backlinks
        // and the graph (center) is no longer squeezed by a wide list.
        <div className="mt-4 grid gap-4 lg:grid-cols-[220px_minmax(0,1.4fr)_minmax(0,1.6fr)]">
          {/* LEFT — note list */}
          <Card
            className={cn(
              "flex max-h-[calc(100vh-12rem)] flex-col overflow-hidden p-3",
              selectedNote && "hidden lg:flex",
            )}
          >
            <div className="relative mb-2">
              <Search className="text-muted-foreground absolute start-2 top-1/2 size-3.5 -translate-y-1/2" aria-hidden />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={copy.searchPlaceholder}
                className="h-8 ps-7 text-sm"
              />
            </div>
            <ul className="flex-1 overflow-y-auto">
              {filteredNotes.length === 0 ? (
                <li className="text-muted-foreground px-2 py-4 text-center text-xs">
                  {workspaceQuery.isLoading ? "…" : copy.empty}
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

          {/* CENTER — graph (hidden on small screens to focus on detail) */}
          <Card
            className={cn(
              "flex max-h-[calc(100vh-12rem)] flex-col p-3",
              "hidden lg:flex",
            )}
          >
            {graphNodes.length === 0 ? (
              <p className="text-muted-foreground py-10 text-center text-sm">
                {copy.noGraph}
              </p>
            ) : (
              <div className="min-h-0 flex-1">
                <MemoryGraphPanel
                  nodes={graphNodes}
                  edges={graphEdges}
                  onNodeClick={handleGraphNode}
                />
              </div>
            )}
          </Card>

          {/* RIGHT — selected note detail + backlinks */}
          <Card
            className={cn(
              "flex max-h-[calc(100vh-12rem)] flex-col overflow-hidden p-4",
              !selectedNote && "hidden lg:flex",
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
      )}
    </AppShell>
  );
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
