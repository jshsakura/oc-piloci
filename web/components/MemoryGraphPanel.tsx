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
  /** Fires whenever the explicit graph focus changes — the actively-clicked
   *  node, or null when the user toggles off / clicks empty canvas. Parent
   *  can use this to narrow the list to 1-hop notes of the focused node. */
  onActiveChange?: (node: GraphNode | null) => void;
  /** Empty-canvas click. Parent can use this as a "reset" gesture (clear
   *  filters, drop the open note, return to the overview). */
  onBackgroundClick?: () => void;
  /** Currently selected node — painted with a ring overlay so the user can
   *  see which point on the map matches the open detail pane. */
  selectedNodeId?: string | null;
}

const KIND_COLOR: Record<GraphNode["kind"], string> = {
  project: "#6366f1",
  note: "#10b981",
  tag: "#facc15",
  topic: "#8b5cf6",
  team: "#0ea5e9",
  folder: "#fb7185",
  doc: "#16a34a",
  file: "#94a3b8",
  article: "#f59e0b",
};

const KIND_LABEL: Record<GraphNode["kind"], string> = {
  project: "프로젝트",
  note: "기억",
  tag: "태그",
  topic: "주제",
  team: "팀",
  folder: "폴더",
  doc: "문서",
  file: "파일",
  article: "위키 글",
};

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function MemoryGraphPanel({
  nodes,
  edges,
  onNodeClick,
  onActiveChange,
  onBackgroundClick,
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

  // Two separate visual states so the graph doesn't feel "always dimmed":
  //   - activeClick: user explicitly clicked a node here on the graph
  //     ➜ ring + 1-hop neighborhood highlighted, everything else dims
  //     ➜ click same node again or click empty canvas to clear
  //   - selectedNodeId (from parent ?note=): a note is open in the detail
  //     pane → ring ONLY for orientation, no dim. Keeps the map readable
  //     while reading a note via the list.
  const [activeClick, setActiveClick] = useState<string | null>(null);

  // 1-hop neighborhood of the actively-clicked node. Only populated while
  // the user has an explicit click active — list-driven note selection
  // does NOT engage the dim layer.
  const highlightNeighbors = useMemo<Set<string> | null>(() => {
    if (!activeClick) return null;
    const set = new Set<string>([activeClick]);
    for (const e of edges) {
      const s = typeof e.source === "string" ? e.source : (e.source as any)?.id;
      const t = typeof e.target === "string" ? e.target : (e.target as any)?.id;
      if (s === activeClick && t) set.add(t);
      if (t === activeClick && s) set.add(s);
    }
    return set;
  }, [activeClick, edges]);

  const nodeColor = useCallback(
    (node: any) => {
      const base = KIND_COLOR[node.kind as GraphNode["kind"]] ?? "#94a3b8";
      if (highlightNeighbors && !highlightNeighbors.has(node.id)) {
        return hexToRgba(base, 0.18);
      }
      return base;
    },
    [highlightNeighbors],
  );

  const linkColor = useCallback(
    (link: any) => {
      if (!activeClick) return "rgba(148,163,184,0.35)";
      const s = typeof link.source === "string" ? link.source : link.source?.id;
      const t = typeof link.target === "string" ? link.target : link.target?.id;
      const touches = s === activeClick || t === activeClick;
      return touches ? "rgba(148,163,184,0.6)" : "rgba(148,163,184,0.08)";
    },
    [activeClick],
  );

  const nodeLabel = useCallback((node: any) => node.label as string, []);

  const handleNodeClick = useCallback(
    (node: any) => {
      // Click the SAME node again → toggle the highlight off (simple "undo
      // dim" without hunting for a control). No pin, no camera pan.
      setActiveClick((prev) => {
        const next = prev === node.id ? null : node.id;
        onActiveChange?.(next ? (node as GraphNode) : null);
        return next;
      });
      onNodeClick?.(node as GraphNode);
    },
    [onNodeClick, onActiveChange],
  );

  // Empty-canvas click clears the local highlight AND forwards to the
  // parent, so the page can use the same gesture as a "reset to overview"
  // (clear tag filter, drop open note, etc.).
  const handleBackgroundClick = useCallback(() => {
    setActiveClick(null);
    onActiveChange?.(null);
    onBackgroundClick?.();
  }, [onActiveChange, onBackgroundClick]);

  // Ring is shown for either the actively-clicked node OR the parent-open
  // note. The ring is the orientation cue; the dim layer is gated on
  // activeClick only.
  const ringIdRef = useRef<string | null>(null);
  ringIdRef.current = activeClick ?? selectedNodeId ?? null;
  const nodeCanvasObjectMode = useCallback(() => "after" as const, []);
  const nodeCanvasObject = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (node.id !== ringIdRef.current) return;
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

  // After the d3 sim cools the canvas stops repainting, so a highlight /
  // ring change alone wouldn't redraw. Nudge force-graph one frame on
  // either trigger.
  useEffect(() => {
    graphRef.current?.refresh?.();
  }, [activeClick, selectedNodeId]);

  // Measure the panel container ourselves and pass the size to ForceGraph2D
  // as explicit pixels. Without this, react-force-graph defaults to window
  // dimensions when width/height are undefined — on mobile that produced a
  // canvas larger than the actual panel viewport, so half the graph was
  // clipped on mount. ResizeObserver also keeps the canvas in sync with
  // orientation / viewport changes after mount.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setSize((prev) =>
        prev.width === rect.width && prev.height === rect.height
          ? prev
          : { width: rect.width, height: rect.height },
      );
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Auto-fit ONCE per graph dataset, but only after BOTH the engine has
  // stopped AND the container has been measured — otherwise zoomToFit runs
  // against a 0x0 (or stale window-sized) canvas and produces a useless
  // camera. The two-condition gate is what cleans up the mobile "half
  // clipped" symptom.
  const hasAutoFitRef = useRef(false);
  const engineStoppedRef = useRef(false);
  useEffect(() => {
    hasAutoFitRef.current = false;
    engineStoppedRef.current = false;
  }, [graphData]);
  const tryAutoFit = useCallback(() => {
    if (hasAutoFitRef.current) return;
    if (!engineStoppedRef.current) return;
    if (size.width < 10 || size.height < 10) return;
    hasAutoFitRef.current = true;
    graphRef.current?.zoomToFit(400, 20);
  }, [size.width, size.height]);
  useEffect(() => {
    tryAutoFit();
  }, [tryAutoFit]);
  const handleEngineStop = useCallback(() => {
    engineStoppedRef.current = true;
    tryAutoFit();
  }, [tryAutoFit]);

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
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
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
          onClick={() => graphRef.current?.zoomToFit(400, 20)}
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
        linkColor={linkColor}
        linkWidth={1}
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={1.5}
        linkDirectionalParticleColor={() => "rgba(148,163,184,0.6)"}
        onNodeClick={handleNodeClick}
        onBackgroundClick={handleBackgroundClick}
        onNodeHover={handleNodeHover}
        nodeCanvasObjectMode={nodeCanvasObjectMode}
        nodeCanvasObject={nodeCanvasObject}
        onEngineStop={handleEngineStop}
        // warmupTicks runs the d3 sim off-screen before frame 0 — by the
        // time the user sees the graph it's already at near-final positions.
        // cooldownTicks then trims the visible-settling window from ~6s to
        // under a second so the map doesn't appear to "fly around" on mount,
        // especially on mobile where small movements look exaggerated.
        warmupTicks={150}
        cooldownTicks={30}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.4}
        backgroundColor="transparent"
        width={size.width || undefined}
        height={size.height || undefined}
      />
    </div>
  );
}
