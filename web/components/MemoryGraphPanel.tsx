"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ZoomIn, ZoomOut, Maximize2, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { GraphNode, GraphEdge } from "@/lib/types";

// react-force-graph-2d uses browser APIs — skip SSR
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

interface MemoryGraphPanelProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick?: (node: GraphNode) => void;
  /** Currently selected node — painted with a ring overlay so the user can
   *  see which point on the map matches the open detail pane. */
  selectedNodeId?: string | null;
}

const KIND_COLOR: Record<GraphNode["kind"], string> = {
  project: "#6366f1",
  note: "#10b981",
  tag: "#f59e0b",
  topic: "#8b5cf6",
};

const KIND_LABEL: Record<GraphNode["kind"], string> = {
  project: "프로젝트",
  note: "기억",
  tag: "태그",
  topic: "주제",
};

export function MemoryGraphPanel({
  nodes,
  edges,
  onNodeClick,
  selectedNodeId,
}: MemoryGraphPanelProps) {
  const graphRef = useRef<any>(null);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  // Tracks the node id under the cursor so the hover handler can short-circuit
  // when force-graph fires the same node repeatedly on every mouse move.
  const hoveredIdRef = useRef<string | null>(null);

  // react-force-graph-2d treats a new graphData object as "the graph changed"
  // and reinitializes the d3 physics — keep the reference stable across
  // unrelated parent re-renders (hover, theme, layout) so the simulation
  // doesn't restart whenever the user wiggles the mouse.
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((n) => ({
        ...n,
        val: n.kind === "project" ? 6 : n.kind === "topic" ? 4 : 2,
      })),
      links: edges.map((e) => ({ source: e.source, target: e.target, kind: e.kind })),
    }),
    [nodes, edges],
  );

  const nodeColor = useCallback(
    (node: any) => KIND_COLOR[node.kind as GraphNode["kind"]] ?? "#94a3b8",
    [],
  );

  const nodeLabel = useCallback((node: any) => node.label as string, []);

  const handleNodeClick = useCallback(
    (node: any) => {
      // Pin the clicked node at its current position. Without this, d3 keeps
      // ticking and the node drifts under the camera mid-animation, which is
      // what made the previous click feel "focus-loose" — you'd click a node
      // and watch it slide away from the center you just panned to.
      node.fx = node.x;
      node.fy = node.y;
      onNodeClick?.(node as GraphNode);
      // Soft pan only — keep the user's zoom level. Snapping to an absolute
      // zoom (the old `zoom(2.5)`) yanked the view in/out depending on where
      // they had zoomed manually, which felt jarring on every click.
      graphRef.current?.centerAt(node.x, node.y, 450);
    },
    [onNodeClick],
  );

  // Paint a ring around the selected node so the click feels like it locks
  // onto a real anchor on the map. Drawn "after" the default node paint so
  // the ring sits on top of the dot. The ref-based lookup avoids re-creating
  // the callback (which would prompt force-graph to rebind props) every
  // selection change — we just refresh the canvas instead.
  const selectedRef = useRef<string | null | undefined>(selectedNodeId);
  selectedRef.current = selectedNodeId;
  const nodeCanvasObjectMode = useCallback(() => "after" as const, []);
  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (node.id !== selectedRef.current) return;
      const baseR = Math.sqrt((node.val as number) ?? 2) * 5;
      const ringR = baseR + 4 / globalScale;
      ctx.beginPath();
      ctx.arc(node.x, node.y, ringR, 0, 2 * Math.PI);
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    },
    [],
  );

  // After the d3 sim cools the canvas stops repainting, so a selection change
  // alone wouldn't redraw the ring. Nudge force-graph to repaint one frame.
  useEffect(() => {
    graphRef.current?.refresh?.();
  }, [selectedNodeId]);

  // onNodeHover fires on every mouse-move while the cursor is over the canvas,
  // not just on enter/leave. Short-circuit when the node id hasn't changed —
  // otherwise a single hover triggers a setState per frame and React re-renders
  // the tooltip + all parent listeners 30+ times per second.
  const handleNodeHover = useCallback((node: any) => {
    const nextId = (node?.id as string | undefined) ?? null;
    if (hoveredIdRef.current === nextId) return;
    hoveredIdRef.current = nextId;
    setHovered(node ? (node as GraphNode) : null);
  }, []);

  if (nodes.length === 0) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-muted-foreground">
        <Info className="size-8" />
        <p className="text-sm">기억이 쌓이면 맥락 지도가 여기에 그려집니다.</p>
      </div>
    );
  }

  // Panel fills its parent — callers own the sizing & chrome (rounded, border,
  // bg). v0.3.62: the wiki page wraps the graph in its own card; rendering
  // another card here produced a clipped, card-inside-card top section.
  return (
    <div className="relative h-full w-full overflow-hidden">
      {/* Controls */}
      <div className="absolute right-3 top-3 z-10 flex flex-col gap-1.5">
        <Button
          size="icon"
          variant="outline"
          className="size-8 bg-background/80 backdrop-blur"
          onClick={() => graphRef.current?.zoom(graphRef.current.zoom() * 1.3, 300)}
        >
          <ZoomIn className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="outline"
          className="size-8 bg-background/80 backdrop-blur"
          onClick={() => graphRef.current?.zoom(graphRef.current.zoom() * 0.77, 300)}
        >
          <ZoomOut className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="outline"
          className="size-8 bg-background/80 backdrop-blur"
          onClick={() => graphRef.current?.zoomToFit(400, 40)}
        >
          <Maximize2 className="size-4" />
        </Button>
      </div>

      {/* Legend */}
      <div className="absolute bottom-3 left-3 z-10 flex flex-wrap gap-1.5">
        {(Object.keys(KIND_COLOR) as GraphNode["kind"][]).map((kind) => (
          <Badge
            key={kind}
            variant="outline"
            className="gap-1 bg-background/80 backdrop-blur text-xs py-0.5"
          >
            <span
              className="inline-block size-2 rounded-full"
              style={{ backgroundColor: KIND_COLOR[kind] }}
            />
            {KIND_LABEL[kind]}
          </Badge>
        ))}
      </div>

      {/* Hover tooltip */}
      {hovered && (
        <div className="absolute left-3 top-3 z-10 max-w-[200px] rounded-lg border bg-background/90 px-3 py-2 text-xs backdrop-blur shadow-md">
          <p className="font-medium truncate">{hovered.label}</p>
          <p className="text-muted-foreground mt-0.5">{KIND_LABEL[hovered.kind]}</p>
        </div>
      )}

      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        nodeId="id"
        nodeLabel={nodeLabel}
        nodeColor={nodeColor}
        nodeRelSize={5}
        linkColor={() => "rgba(148,163,184,0.35)"}
        linkWidth={1}
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleColor={() => "rgba(148,163,184,0.6)"}
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        nodeCanvasObjectMode={nodeCanvasObjectMode}
        nodeCanvasObject={nodeCanvasObject}
        onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
        cooldownTicks={120}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.35}
        backgroundColor="transparent"
      />
    </div>
  );
}
