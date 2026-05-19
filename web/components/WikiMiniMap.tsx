"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, Minimize2, Map as MapIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
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
};

interface WikiMiniMapProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Article currently being read — its sources get a highlight ring on the
   *  map so the user can locate them spatially. */
  highlightedIds?: string[];
  /** Fires when a node is clicked. Parent can sync the article reader. */
  onNodeClick?: (node: GraphNode) => void;
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
export function WikiMiniMap({ nodes, edges, highlightedIds = [], onNodeClick }: WikiMiniMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [hidden, setHidden] = useState(false);
  // Hover label stays inside the card — react-force-graph's default tooltip
  // is an HTML overlay anchored to mouse coords that falls outside the
  // small floating panel (user reported "툴팁이 좌측으로 나온다").
  const [hovered, setHovered] = useState<GraphNode | null>(null);

  const highlightSet = useMemo(() => new Set(highlightedIds), [highlightedIds]);

  // Stable graphData reference so the d3 simulation doesn't restart on every
  // parent re-render. react-force-graph treats a new object literal as a
  // brand-new graph and re-seeds positions — bad UX while the user is reading.
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({
        ...n,
        val: n.kind === "team" ? 6 : n.kind === "folder" ? 3 : 2,
      })),
      links: edges.map((e) => ({ source: e.source, target: e.target, kind: e.kind })),
    }),
    [nodes, edges],
  );

  // Density guard: hide the map automatically when the graph has too many
  // nodes to be useful in a small canvas. The user can still toggle it back
  // on, but we don't insist on rendering a hairball by default.
  useEffect(() => {
    if (nodes.length > 400) setHidden(true);
  }, [nodes.length]);

  if (hidden) {
    return (
      <div className="fixed right-4 top-20 z-30">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setHidden(false)}
          className="shadow-md"
        >
          <MapIcon className="me-2 size-4" /> 지도 보기
        </Button>
      </div>
    );
  }

  const width = expanded ? 480 : 256;
  const height = expanded ? 320 : 170;

  return (
    <div
      ref={containerRef}
      className="fixed right-4 top-20 z-30 hidden overflow-hidden rounded-xl border bg-background/95 shadow-lg backdrop-blur sm:block"
      style={{ width, height }}
    >
      <div className="flex items-center justify-between border-b px-2 py-1 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <MapIcon className="size-3" /> 맥락 지도
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="rounded hover:bg-accent"
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "줄이기" : "넓히기"}
          >
            {expanded ? <Minimize2 className="size-3" /> : <Maximize2 className="size-3" />}
          </button>
          <button
            type="button"
            className="rounded px-1 hover:bg-accent"
            onClick={() => setHidden(true)}
            title="숨기기"
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
