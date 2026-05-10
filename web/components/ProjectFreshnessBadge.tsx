"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

interface Props {
  projectId: string;
}

/**
 * Compact one-line freshness indicator for project cards.
 *
 * Three visual states map to the three states the user actually cares about:
 *   green check  → no pending work, fully distilled
 *   amber clock  → some pending, but lag is reasonable (< 6h)
 *   red warning  → backlog is genuinely behind (≥ 6h or > 10 pending)
 *
 * Polled every 30 seconds — enough to feel live without hammering the Pi.
 */
export function ProjectFreshnessBadge({ projectId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["projectFreshness", projectId],
    queryFn: () => api.projectFreshness(projectId),
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  if (isLoading || !data) {
    return null;
  }

  const pending = data.pending_count;
  const lagSec = data.oldest_pending_age_seconds ?? 0;
  const lagHours = lagSec / 3600;

  if (pending === 0) {
    return (
      <Badge variant="outline" className="inline-flex items-center gap-1 text-xs">
        <CheckCircle2 className="size-3 text-emerald-500" />
        최신
      </Badge>
    );
  }

  if (lagHours >= 6 || pending > 10) {
    return (
      <Badge
        variant="outline"
        className="inline-flex items-center gap-1 border-amber-500 text-xs text-amber-600 dark:text-amber-400"
      >
        <AlertTriangle className="size-3" />
        {Math.round(lagHours)}h 지연 ({pending})
      </Badge>
    );
  }

  return (
    <Badge variant="outline" className="inline-flex items-center gap-1 text-xs">
      <Clock className="size-3 text-muted-foreground" />
      {pending}개 대기
    </Badge>
  );
}
