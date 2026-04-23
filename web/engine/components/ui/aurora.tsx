import * as React from "react";
import { cn } from "./utils";

export function Aurora({ className }: { className?: string }) {
  return (
    <div className={cn("fixed inset-0 pointer-events-none overflow-hidden", className)}>
      <div className="aurora-engine" />
      <div className="aura-spotlight" />
    </div>
  );
}
