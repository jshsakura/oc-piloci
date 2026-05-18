import { ReactNode } from "react";
import { LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Reusable shell for cards that share the same loading skeleton shape:
 * a title row plus N rectangular skeleton blocks of a configurable
 * height. Keeps the visual idiom consistent across DistillationStatus,
 * RecentSessions, TeamMini, WeeklyDigest, etc. so layout doesn't shift
 * when data lands.
 */
export function LoadingCard({
  title,
  icon: Icon,
  rows = 3,
  rowHeight = "h-14",
}: {
  title: string;
  icon?: LucideIcon;
  rows?: number;
  rowHeight?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {Icon && <Icon className="text-muted-foreground size-4" aria-hidden />}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className={rowHeight} />
        ))}
      </CardContent>
    </Card>
  );
}

/** Bare skeleton block — for cards that already manage their own
 *  header but want a placeholder body during loading. */
export function SkeletonBlock({ rows = 3, rowHeight = "h-14" }: { rows?: number; rowHeight?: string }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={rowHeight} />
      ))}
    </div>
  );
}

export function SkeletonGrid({
  cols = 3,
  count = 3,
  itemHeight = "h-14",
}: {
  cols?: number;
  count?: number;
  itemHeight?: string;
}) {
  return (
    <div className={`grid gap-2 grid-cols-${cols}`}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={itemHeight} />
      ))}
    </div>
  );
}

export function CardShell({ children }: { children: ReactNode }) {
  return <Card>{children}</Card>;
}
