import * as React from "react";
import { cn } from "./utils";

interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  beam?: boolean;
}

export function GlassCard({ className, beam = false, children, ...props }: GlassCardProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-pro border border-border-mute bg-surface-card backdrop-blur-2xl transition-all duration-500",
        className
      )}
      {...props}
    >
      {beam && <div className="border-beam-engine opacity-40" />}
      <div className="relative z-10">{children}</div>
    </div>
  );
}
