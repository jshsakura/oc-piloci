"use client";

import dynamic from "next/dynamic";
import { useCallback, useRef, useState } from "react";
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

export function MemoryGraphPanel({ nodes, edges, onNodeClick }: MemoryGraphPanelProps) {
  const graphRef = useRef<any>(null);
  const [hovered, setHovered] = useState<GraphNode | null>(null);

  const graphData = {
    nodes: nodes.map((n) => ({ ...n, val: n.kind === "project" ? 6 : n.kind === "topic" ? 4 : 2 })),
    links: edges.map((e) => ({ source: e.source, target: e.target, kind: e.kind })),
  };

  const nodeColor = useCallback((node: any) => KIND_COLOR[node.kind as GraphNode["kind"]] ?? "#94a3b8", []);

  const nodeLabel = useCallback((node: any) => node.label as string, []);

  const handleNodeClick = useCallback(
    (node: any) => {
      onNodeClick?.(node as GraphNode);
      graphRef.current?.centerAt(node.x, node.y, 400);
      graphRef.current?.zoom(2.5, 400);
    },
    [onNodeClick],
  );

  const handleNodeHover = useCallback((node: any) => {
    setHovered(node ? (node as GraphNode) : null);
  }, []);

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
        <Info className="size-8" />
        <p className="text-sm">기억이 쌓이면 맥락 지도가 여기에 그려집니다.</p>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-xl border bg-card" style={{ height: "520px" }}>
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
        cooldownTicks={120}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.35}
        backgroundColor="transparent"
        width={undefined}
        height={520}
      />
    </div>
  );
}
