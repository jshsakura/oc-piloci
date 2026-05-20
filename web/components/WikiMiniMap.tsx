"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GripVertical, Maximize2, Minimize2, Map as MapIcon } from "lucide-react";

import { useTranslation } from "@/lib/i18n";
import type { GraphEdge, GraphNode } from "@/lib/types";

// react-force-graph relies on browser canvas APIs — SSR is a no-go.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

const KIND_COLOR: Record<GraphNode["kind"], string> = {
  project: "#6366f1",
  note: "#10b981",
  tag: "#facc15",
  topic: "#8b5cf6",
  team: "#0ea5e9",
  // folder vs doc was slate-gray vs green — too close in dark mode. Bumped
  // folder to a warm coral so the filesystem skeleton stands out from the
  // green doc-leaves at a glance.
  folder: "#fb7185",
  doc: "#16a34a",
  file: "#94a3b8",
  // Wiki articles are the headline nodes — a bright amber so they pop out of
  // the doc/memory substrate as the "real" wiki layer.
  article: "#f59e0b",
};

interface WikiMiniMapProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Article currently being read — its sources get a highlight ring on the
   *  map so the user can locate them spatially. */
  highlightedIds?: string[];
  /** Fires when a node is clicked. Parent can sync the article reader. */
  onNodeClick?: (node: GraphNode) => void;
  /** Controlled hidden state — the show/hide toggle now lives in the wiki
   *  page header, so visibility is owned by the parent. */
  hidden?: boolean;
  /** Lets the map ask the parent to hide itself (× button, density guard). */
  onHiddenChange?: (hidden: boolean) => void;
  /** Inline mode: render full-width inside a tab instead of floating in the
   *  top-right corner. No drag, no hide button, no density auto-dismiss. */
  inline?: boolean;
}

/**
 * Top-right floating mini-map for the team wiki page. Tiny by default (256×170)
 * so it doesn't fight the article reader, but the user can expand it to a
 * larger panel (480×320) if they want to navigate the graph as the primary
 * gesture.
 *
 * The map is read-only — actual edits happen elsewhere (manual article build,
 * doc upload). Its purpose is "spatial breadcrumb": see how the article you're
 * reading connects to the rest of the team's knowledge.
 */
export function WikiMiniMap({
  nodes,
  edges,
  highlightedIds = [],
  onNodeClick,
  hidden = false,
  onHiddenChange,
  inline = false,
}: WikiMiniMapProps) {
  const { t } = useTranslation();
  const copy = t.teams.map;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [inlineSize, setInlineSize] = useState({ width: 640, height: 460 });
  const setHidden = useCallback(
    (next: boolean) => onHiddenChange?.(next),
    [onHiddenChange],
  );
  // Hover label stays inside the card — react-force-graph's default tooltip
  // is an HTML overlay anchored to mouse coords that falls outside the
  // small floating panel (user reported "툴팁이 좌측으로 나온다").
  const [hovered, setHovered] = useState<GraphNode | null>(null);

  // Desktop-only drag offset from the default top-right anchor. Deliberately
  // NOT persisted: every fresh mount/reopen starts at {0,0} so the map snaps
  // back to its default corner — the dragged spot is a temporary convenience,
  // not a saved preference.
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(
    null,
  );

  // Reset the offset whenever the panel re-mounts or comes back from hidden,
  // so reopening always returns to the default corner.
  useEffect(() => {
    if (!hidden) setOffset({ x: 0, y: 0 });
  }, [hidden]);

  const handleDragPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // Pointer-fine guard: only mice/trackpads get drag. Touch/coarse
      // pointers (mobile, tablet) keep the panel anchored.
      if (typeof window !== "undefined" && !window.matchMedia("(pointer: fine)").matches) {
        return;
      }
      event.preventDefault();
      dragRef.current = {
        startX: event.clientX,
        startY: event.clientY,
        baseX: offset.x,
        baseY: offset.y,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [offset.x, offset.y],
  );

  const handleDragPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    setOffset({
      x: drag.baseX + (event.clientX - drag.startX),
      y: drag.baseY + (event.clientY - drag.startY),
    });
  }, []);

  const handleDragPointerUp = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const highlightSet = useMemo(() => new Set(highlightedIds), [highlightedIds]);

  // Stable graphData reference so the d3 simulation doesn't restart on every
  // parent re-render. react-force-graph treats a new object literal as a
  // brand-new graph and re-seeds positions — bad UX while the user is reading.
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({
        ...n,
        val: n.kind === "team" ? 6 : n.kind === "article" ? 4 : n.kind === "folder" ? 3 : 2,
      })),
      links: edges.map((e) => ({ source: e.source, target: e.target, kind: e.kind })),
    }),
    [nodes, edges],
  );

  // Inline mode tracks its container width so the canvas fills the tab.
  useEffect(() => {
    if (!inline) return;
    const el = containerRef.current;
    if (!el) return;
    const measure = () =>
      setInlineSize({ width: el.clientWidth, height: Math.max(360, el.clientHeight) });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [inline]);

  if (inline) {
    return (
      <div
        ref={containerRef}
        className="relative h-[60vh] min-h-[360px] w-full overflow-hidden rounded-xl border bg-background/40"
      >
        <ForceGraph2D
          graphData={graphData}
          width={inlineSize.width}
          height={inlineSize.height}
          nodeRelSize={4}
          linkWidth={0.6}
          linkColor={() => "rgba(148,163,184,0.5)"}
          cooldownTicks={80}
          enableNodeDrag={false}
          nodeLabel={() => ""}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D) => {
            const color = KIND_COLOR[node.kind as GraphNode["kind"]] ?? "#94a3b8";
            const radius = node.val ?? 2;
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.fill();
            if (highlightSet.has(node.id)) {
              ctx.lineWidth = 1.4;
              ctx.strokeStyle = "#f43f5e";
              ctx.stroke();
            }
          }}
          onNodeHover={(node: any) => setHovered((node as GraphNode) ?? null)}
          onNodeClick={(node: any) => {
            // Touch devices have no hover, so a tap reveals the node's label
            // (lets the user read the map) *before* delegating. The parent
            // decides whether the tap also navigates/closes the sheet.
            setHovered(node as GraphNode);
            if (onNodeClick) onNodeClick(node as GraphNode);
          }}
        />
        {hovered && (
          <div className="absolute inset-x-2 bottom-2 truncate rounded bg-background/90 px-3 py-1.5 text-xs font-medium shadow-sm backdrop-blur">
            <span
              className="me-1.5 inline-block size-2 rounded-full align-middle"
              style={{ backgroundColor: KIND_COLOR[hovered.kind] ?? "#94a3b8" }}
            />
            {hovered.label}
          </div>
        )}
      </div>
    );
  }

  if (hidden) return null;

  const width = expanded ? 480 : 256;
  const height = expanded ? 320 : 170;

  return (
    <div
      ref={containerRef}
      className="fixed right-4 top-44 z-30 hidden overflow-hidden rounded-xl border bg-background/70 shadow-lg backdrop-blur sm:block"
      style={{ width, height, transform: `translate(${offset.x}px, ${offset.y}px)` }}
    >
      <div
        className="flex touch-none select-none items-center justify-between border-b px-2 py-1 text-[11px] text-muted-foreground sm:cursor-grab sm:active:cursor-grabbing"
        onPointerDown={handleDragPointerDown}
        onPointerMove={handleDragPointerMove}
        onPointerUp={handleDragPointerUp}
        onPointerCancel={handleDragPointerUp}
      >
        <span className="flex items-center gap-1">
          <GripVertical className="size-3 opacity-50" />
          <MapIcon className="size-3" /> {copy.title}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="rounded hover:bg-accent"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? copy.shrink : copy.expand}
          >
            {expanded ? <Minimize2 className="size-3" /> : <Maximize2 className="size-3" />}
          </button>
          <button
            type="button"
            className="rounded px-1 hover:bg-accent"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => setHidden(true)}
            title={copy.hide}
          >
            ×
          </button>
        </div>
      </div>
      <div className="relative" style={{ width, height: height - 22 }}>
        <ForceGraph2D
          graphData={graphData}
          width={width}
          height={height - 22}
          nodeRelSize={3}
          linkWidth={0.5}
          linkColor={() => "rgba(148,163,184,0.5)"}
          cooldownTicks={60}
          enableNodeDrag={false}
          // nodeLabel="" disables the default HTML tooltip that mispositions
          // when the canvas lives inside a small fixed-position card. We
          // render our own hover bar in the bottom-left of the card instead.
          nodeLabel={() => ""}
          nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D) => {
            const color = KIND_COLOR[node.kind as GraphNode["kind"]] ?? "#94a3b8";
            const radius = node.val ?? 2;
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.fill();
            if (highlightSet.has(node.id)) {
              ctx.lineWidth = 1.2;
              ctx.strokeStyle = "#f43f5e";
              ctx.stroke();
            }
          }}
          onNodeHover={(node: any) => setHovered((node as GraphNode) ?? null)}
          onNodeClick={(node: any) => {
            if (onNodeClick) onNodeClick(node as GraphNode);
          }}
        />
        {hovered && (
          <div className="pointer-events-none absolute inset-x-1 bottom-1 truncate rounded bg-background/90 px-2 py-1 text-[11px] font-medium shadow-sm backdrop-blur">
            <span
              className="me-1 inline-block size-2 rounded-full align-middle"
              style={{ backgroundColor: KIND_COLOR[hovered.kind] ?? "#94a3b8" }}
            />
            {hovered.label}
          </div>
        )}
      </div>
    </div>
  );
}
