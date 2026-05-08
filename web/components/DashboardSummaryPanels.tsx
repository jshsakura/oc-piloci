"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Brain,
  FileText,
  Hash,
  Lightbulb,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  totalMemories: number;
  totalKnacks: number;
  projectCount: number;
}

function StatPill({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: number | string;
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-md border bg-card px-3 py-2">
      <Icon className="size-4 shrink-0 text-primary" />
      <div className="min-w-0">
        <p className="truncate text-xs text-muted-foreground">{label}</p>
        <p className="truncate text-base font-semibold tabular-nums">{value}</p>
      </div>
    </div>
  );
}

function ActivitySparkline({ buckets }: { buckets: { date: string; count: number }[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <div className="flex h-16 items-end gap-[2px]">
      {buckets.map((b) => {
        const h = b.count === 0 ? 4 : Math.max(6, Math.round((b.count / max) * 100));
        return (
          <div
            key={b.date}
            className={`flex-1 rounded-sm transition-colors ${
              b.count > 0 ? "bg-primary/70 hover:bg-primary" : "bg-muted"
            }`}
            style={{ height: `${h}%` }}
            title={`${b.date}: ${b.count}`}
          />
        );
      })}
    </div>
  );
}

export function DashboardSummaryPanels({ totalMemories, totalKnacks, projectCount }: Props) {
  const { t, locale } = useTranslation();
  const summary = t.dashboard.summary;

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: api.dashboardSummary,
  });

  const dateFmt = (iso: string) => new Date(iso).toLocaleDateString(locale);
  const timeFmt = (iso: string) =>
    new Date(iso).toLocaleString(locale, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <div className="mt-6 space-y-4">
      {/* Compact stat strip + activity sparkline */}
      <Card>
        <CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center">
          <div className="grid grid-cols-3 gap-2 lg:w-auto">
            <StatPill icon={FileText} label={t.dashboard.stats.projects} value={projectCount} />
            <StatPill icon={Brain} label={t.dashboard.stats.totalMemories} value={totalMemories} />
            <StatPill icon={Lightbulb} label={t.dashboard.stats.totalKnacks} value={totalKnacks} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex items-center justify-between text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Activity className="size-3" />
                {summary.activityTitle}
              </span>
            </div>
            {isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : !data?.activity?.length ? (
              <p className="py-5 text-center text-xs text-muted-foreground">{summary.activityEmpty}</p>
            ) : (
              <ActivitySparkline buckets={data.activity} />
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recent memories */}
        <Card>
          <CardContent className="p-4">
            <h3 className="mb-3 inline-flex items-center gap-1.5 text-sm font-semibold">
              <Brain className="size-4 text-primary" /> {summary.recentMemoriesTitle}
            </h3>
            {isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : !data?.recent_memories?.length ? (
              <p className="py-6 text-center text-xs text-muted-foreground">
                {summary.recentMemoriesEmpty}
              </p>
            ) : (
              <ul className="space-y-2">
                {data.recent_memories.map((m) => (
                  <li key={m.memory_id}>
                    <Link
                      href={`/projects/?slug=${m.project_slug}`}
                      className="block min-w-0 rounded-md border bg-card px-3 py-2 transition-colors hover:bg-accent"
                    >
                      <p className="line-clamp-2 break-words text-sm">{m.content}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                        <Badge variant="secondary" className="text-[10px]">
                          {m.project_slug}
                        </Badge>
                        {m.tags.slice(0, 3).map((tag) => (
                          <span key={tag} className="inline-flex items-center gap-0.5">
                            <Hash className="size-2.5" />
                            {tag}
                          </span>
                        ))}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {/* Top knacks */}
        <Card>
          <CardContent className="p-4">
            <h3 className="mb-3 inline-flex items-center gap-1.5 text-sm font-semibold">
              <Lightbulb className="size-4 text-primary" /> {summary.topKnacksTitle}
            </h3>
            {isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : !data?.top_instincts?.length ? (
              <p className="py-6 text-center text-xs text-muted-foreground">
                {summary.topKnacksEmpty}
              </p>
            ) : (
              <ul className="space-y-2">
                {data.top_instincts.map((i) => (
                  <li
                    key={i.instinct_id}
                    className="rounded-md border bg-card px-3 py-2"
                  >
                    <p className="line-clamp-1 break-words text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">when</span> {i.trigger}
                    </p>
                    <p className="line-clamp-1 break-words text-sm">
                      <span className="font-medium text-primary">→</span> {i.action}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Badge variant="secondary" className="text-[10px]">
                        {i.project_slug}
                      </Badge>
                      <Badge variant="outline" className="text-[10px]">{i.domain}</Badge>
                      <span>×{i.instinct_count}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Bottom row: tags + recent sessions */}
      <div className="grid gap-4 lg:grid-cols-[2fr_3fr]">
        {/* Top tags */}
        <Card>
          <CardContent className="p-4">
            <h3 className="mb-3 inline-flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" /> {summary.topTagsTitle}
            </h3>
            {isLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : !data?.top_tags?.length ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                {summary.topTagsEmpty}
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {data.top_tags.map((t) => (
                  <Badge
                    key={t.tag}
                    variant="secondary"
                    className="break-all"
                  >
                    #{t.tag} <span className="ml-1 opacity-60">×{t.count}</span>
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent sessions */}
        <Card>
          <CardContent className="p-4">
            <h3 className="mb-3 inline-flex items-center gap-1.5 text-sm font-semibold">
              <FileText className="size-4 text-primary" /> {summary.recentSessionsTitle}
            </h3>
            {isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : !data?.recent_sessions?.length ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                {summary.recentSessionsEmpty}
              </p>
            ) : (
              <ul className="divide-y">
                {data.recent_sessions.map((s) => (
                  <li
                    key={s.ingest_id}
                    className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {s.project_slug ? (
                        <Link
                          href={`/projects/?slug=${s.project_slug}`}
                          className="font-medium hover:underline"
                        >
                          {s.project_name}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                      <span className="text-muted-foreground">
                        {s.processed_at
                          ? summary.sessionMemories.replace(
                              "{count}",
                              String(s.memories_extracted),
                            )
                          : summary.sessionPending}
                      </span>
                    </div>
                    <span className="text-muted-foreground">{timeFmt(s.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      {/* dateFmt currently unused — kept here for future expanded views */}
      <div hidden>{dateFmt(new Date().toISOString())}</div>
    </div>
  );
}
