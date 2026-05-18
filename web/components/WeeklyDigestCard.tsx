"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Lock, RefreshCcw, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";

/**
 * Private weekly retrospective. Pulls /api/digests/weekly which the server
 * filters by caller id — feedback memories and reaction instincts that
 * recall hides from MCP are surfaced here, but never shared with teams.
 */
export function WeeklyDigestCard() {
  const { t, locale } = useTranslation();
  const copy = t.dashboard.weeklyDigest;
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["weeklyDigest"],
    queryFn: () => api.getWeeklyDigest(),
    // Once-a-week artifact — cheap to refetch and OK to keep stale across nav.
    staleTime: 5 * 60_000,
  });

  const regenerate = useMutation({
    mutationFn: () => api.regenerateWeeklyDigest(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["weeklyDigest"] });
    },
  });

  const digest = data?.digest ?? null;
  const stats = digest?.stats;

  return (
    <Card className="border-primary/10">
      <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base sm:text-lg">
            <Sparkles className="size-4 text-primary" aria-hidden />
            <span>{copy.title}</span>
            <Badge variant="outline" className="gap-1 text-[10px] font-medium">
              <Lock className="size-3" aria-hidden />
              {copy.privateBadge}
            </Badge>
          </CardTitle>
          <p className="text-muted-foreground text-xs">{copy.privateNote}</p>
        </div>
        {digest && (
          <Button
            variant="ghost"
            size="sm"
            disabled={regenerate.isPending}
            onClick={() => regenerate.mutate()}
            className="self-start"
          >
            <RefreshCcw
              className={`size-3.5 ${regenerate.isPending ? "animate-spin" : ""}`}
              aria-hidden
            />
            <span className="ms-1.5">
              {regenerate.isPending ? copy.regenerating : copy.regenerate}
            </span>
          </Button>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-3 w-40" />
            <Skeleton className="h-16 w-full" />
            <div className="grid grid-cols-3 gap-2">
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
            </div>
          </div>
        )}

        {error && !isLoading && (
          <p className="text-destructive text-sm">{(error as Error).message}</p>
        )}

        {!isLoading && !error && !digest && (
          <div className="flex flex-col items-start gap-3">
            <p className="text-muted-foreground text-sm">{copy.empty}</p>
            <Button
              size="sm"
              variant="secondary"
              disabled={regenerate.isPending}
              onClick={() => regenerate.mutate()}
            >
              <RefreshCcw
                className={`size-3.5 ${regenerate.isPending ? "animate-spin" : ""}`}
                aria-hidden
              />
              <span className="ms-1.5">
                {regenerate.isPending ? copy.regenerating : copy.emptyAction}
              </span>
            </Button>
          </div>
        )}

        {digest && (
          <>
            <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span className="inline-flex items-center gap-1">
                <CalendarDays className="size-3" aria-hidden />
                {copy.weekLabel} {digest.week_start}
              </span>
              <span aria-hidden>·</span>
              <span>
                {copy.generatedAt}:{" "}
                {new Date(digest.generated_at).toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}
              </span>
            </div>

            {/* Korean-first paragraph from Gemma (or the deterministic fallback). */}
            <p className="text-foreground/90 text-sm leading-relaxed whitespace-pre-wrap">
              {digest.summary}
            </p>

            {stats && (
              // v0.3.53: 4 stats, mobile lays them out 2×2 so the row no
              // longer feels under-used. Emerald slot picks up the
              // active-project count from top_projects (already returned
              // by the digest worker — no backend change needed).
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label={copy.statSessions} value={stats.sessions} tone="blue" />
                <Stat label={copy.statFeedback} value={stats.feedback_count} tone="rose" />
                <Stat label={copy.statReactions} value={stats.reaction_count} tone="violet" />
                <Stat
                  label={copy.statProjects}
                  value={stats.top_projects?.length ?? 0}
                  tone="emerald"
                />
              </div>
            )}

            {stats?.top_projects && stats.top_projects.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-muted-foreground text-xs font-medium">{copy.topProjects}</p>
                <div className="flex flex-wrap gap-1.5">
                  {stats.top_projects.map((p) => (
                    <Badge key={p.name} variant="secondary" className="text-xs">
                      {p.name}
                      <span className="text-muted-foreground ms-1">{p.sessions}</span>
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// v0.3.49: stat boxes were nearly invisible in dark mode (bg-muted/40
// against a similarly-muted card background). Use category-coloured
// backgrounds so the three counts are visually distinct and pop in
// both themes without needing a border.
function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "blue" | "rose" | "violet" | "emerald";
}) {
  const toneClass = {
    blue: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
    rose: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
    violet: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
    emerald: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  }[tone];
  return (
    <div className={`rounded-md px-3 py-2 ${toneClass}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
