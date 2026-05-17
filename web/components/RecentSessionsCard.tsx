"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, ExternalLink, Filter, History, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import type { RawSessionListItem } from "@/lib/types";

/**
 * Recent raw_sessions inspector. Sits beside DistillationStatusPanel and
 * answers "what failed / what got extracted from each session?" — the
 * counts alone never told that story. Tab-filtered by state; clicking a
 * row jumps to /projects?slug=… so the user lands in the existing
 * per-project drill-down with the row in context.
 */
type StateFilter = "any" | "failed" | "distilled" | "filtered";

export function RecentSessionsCard() {
  const { t, locale } = useTranslation();
  const copy = t.dashboard.recentSessions;
  const [filter, setFilter] = useState<StateFilter>("any");

  const { data, isLoading, error } = useQuery({
    queryKey: ["recentSessions", filter],
    queryFn: () => api.listRawSessions(filter === "any" ? undefined : filter, 20),
    staleTime: 15_000,
  });

  const sessions = data?.sessions ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="size-4 text-muted-foreground" aria-hidden />
          {copy.title}
        </CardTitle>
        <Tabs value={filter} onValueChange={(v) => setFilter(v as StateFilter)}>
          <TabsList>
            <TabsTrigger value="any" className="text-xs">
              {copy.tabAll}
            </TabsTrigger>
            <TabsTrigger value="distilled" className="text-xs">
              {copy.tabDistilled}
            </TabsTrigger>
            <TabsTrigger value="failed" className="text-xs">
              {copy.tabFailed}
            </TabsTrigger>
            <TabsTrigger value="filtered" className="text-xs">
              {copy.tabFiltered}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent>
        {isLoading && <p className="text-muted-foreground text-sm">···</p>}
        {error && !isLoading && (
          <p className="text-destructive text-sm">{(error as Error).message}</p>
        )}
        {!isLoading && !error && sessions.length === 0 && (
          <p className="text-muted-foreground text-sm">{copy.empty}</p>
        )}
        {sessions.length > 0 && (
          <ul className="divide-border divide-y">
            {sessions.map((s) => (
              <SessionRow key={s.ingest_id} session={s} locale={locale} copy={copy} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

type ReasonMap = Record<string, string>;

function lookupReason(code: string | null | undefined, map: ReasonMap): {
  text: string;
  isUnknown: boolean;
} {
  if (!code) {
    return { text: map.unknown ?? "—", isUnknown: true };
  }
  const known = map[code];
  if (known) {
    return { text: known, isUnknown: false };
  }
  // Unknown code path — surface the raw string so devs can still triage,
  // but flag it so the UI can render the friendly "unknown" prefix.
  return { text: code, isUnknown: true };
}

function SessionRow({
  session,
  locale,
  copy,
}: {
  session: RawSessionListItem;
  locale: string;
  copy: {
    extractedCounts: string;
    pathLocal: string;
    pathExternal: string;
    attempt: string;
    noProject: string;
    openProject: string;
    errorReasons: ReasonMap;
    filterReasons: ReasonMap;
  };
}) {
  const stateBadge = renderStateBadge(session.state);
  const when = session.processed_at ?? session.created_at;
  const whenLabel = when
    ? new Date(when).toLocaleString(locale === "ko" ? "ko-KR" : "en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {stateBadge}
        <span className="text-muted-foreground">{whenLabel}</span>
        <span className="text-muted-foreground">·</span>
        <span className="text-foreground/80">{session.client}</span>
        {session.project_name ? (
          <a
            href={`/projects?slug=${session.project_id}`}
            className="text-primary inline-flex items-center gap-0.5 hover:underline"
          >
            {session.project_name}
            <ExternalLink className="size-3" aria-hidden />
          </a>
        ) : (
          <span className="text-muted-foreground italic">{copy.noProject}</span>
        )}
        {session.processing_path && (
          <Badge variant="outline" className="text-[10px]">
            {session.processing_path === "external" ? copy.pathExternal : copy.pathLocal}
          </Badge>
        )}
        {session.attempt_count > 1 && (
          <Badge variant="outline" className="text-[10px]">
            {copy.attempt} {session.attempt_count}
          </Badge>
        )}
      </div>

      {/* Outcome line — varies by state so the user gets the most useful
          piece up front. */}
      <p className="text-foreground/90 mt-1.5 text-sm">
        {session.state === "distilled" &&
          copy.extractedCounts
            .replace("{memories}", String(session.memories_extracted))
            .replace("{instincts}", String(session.instincts_extracted))}
        {session.state === "failed" && (() => {
          const r = lookupReason(session.error, copy.errorReasons);
          return (
            <span className="text-destructive">
              ⚠ {r.text}
              {r.isUnknown && session.error && (
                // Raw code kept beside the friendly label so the user can
                // ping us with something concrete when they hit an
                // un-translated path.
                <span className="text-muted-foreground/70 ms-1.5 font-mono text-xs">
                  ({session.error})
                </span>
              )}
            </span>
          );
        })()}
        {session.state === "filtered" && (() => {
          const r = lookupReason(session.filter_reason, copy.filterReasons);
          return (
            <span className="text-muted-foreground">
              {r.text}
              {r.isUnknown && session.filter_reason && (
                <span className="ms-1.5 font-mono text-xs">({session.filter_reason})</span>
              )}
            </span>
          );
        })()}
        {session.state === "pending" && (
          <span className="text-muted-foreground">대기 중</span>
        )}
        {session.state === "archived" && (
          <span className="text-muted-foreground">아카이브됨</span>
        )}
      </p>
    </li>
  );
}

function renderStateBadge(state: string) {
  if (state === "distilled")
    return (
      <Badge variant="outline" className="gap-1 border-emerald-500 text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="size-3" /> 정리됨
      </Badge>
    );
  if (state === "failed")
    return (
      <Badge variant="outline" className="gap-1 border-destructive text-destructive">
        <XCircle className="size-3" /> 실패
      </Badge>
    );
  if (state === "filtered")
    return (
      <Badge variant="outline" className="gap-1 text-muted-foreground">
        <Filter className="size-3" /> 필터됨
      </Badge>
    );
  if (state === "pending")
    return (
      <Badge variant="outline" className="gap-1">
        <Clock className="size-3" /> 대기
      </Badge>
    );
  return (
    <Badge variant="outline" className="gap-1 text-muted-foreground">
      <AlertTriangle className="size-3" /> {state}
    </Badge>
  );
}
