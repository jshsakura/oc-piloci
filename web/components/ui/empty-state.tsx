import { ReactNode } from "react";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Centralised empty / error / placeholder state for cards and panels.
 * Pages used to inline their own dashed-border + centred text divs;
 * this gives them one shape so the chrome reads the same everywhere.
 *
 *   <EmptyState>아직 메모리가 없습니다.</EmptyState>
 *   <EmptyState icon={Inbox} action={<Button>...</Button>}>...</EmptyState>
 *   <EmptyState tone="error">불러오지 못했습니다.</EmptyState>
 */
export function EmptyState({
  children,
  icon: Icon,
  action,
  tone = "muted",
  className,
}: {
  children: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
  tone?: "muted" | "error";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "border-border/60 flex flex-col items-center justify-center gap-3 rounded-md border border-dashed px-6 py-10 text-center text-sm",
        tone === "error" ? "text-destructive border-destructive/30" : "text-muted-foreground",
        className,
      )}
    >
      {Icon && <Icon className="size-6 opacity-60" aria-hidden />}
      <p>{children}</p>
      {action}
    </div>
  );
}
