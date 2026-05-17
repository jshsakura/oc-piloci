"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Lock, RefreshCcw, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
          <div className="text-muted-foreground bg-muted/30 h-20 animate-pulse rounded" />
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
              <div className="grid grid-cols-3 gap-2">
                <Stat label={copy.statSessions} value={stats.sessions} />
                <Stat label={copy.statFeedback} value={stats.feedback_count} />
                <Stat label={copy.statReactions} value={stats.reaction_count} />
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

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-muted/40 rounded-md px-3 py-2">
      <p className="text-muted-foreground text-[10px] uppercase tracking-wide">{label}</p>
      <p className="text-foreground text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
