import * as React from "react";
import { cn } from "./utils";

export function AuroraBackground({ className }: { className?: string }) {
  return (
    <>
      <div className={cn("fixed inset-0 bg-aurora pointer-events-none", className)}>
        <div className="aurora-blob aurora-1" />
        <div className="aurora-blob aurora-2" />
        <div className="aurora-blob aurora-3" />
      </div>
      <div className="fixed inset-0 bg-noise pointer-events-none" />
      <div className="fixed inset-0 bg-grid-pattern opacity-[0.05] pointer-events-none" />
    </>
  );
}
