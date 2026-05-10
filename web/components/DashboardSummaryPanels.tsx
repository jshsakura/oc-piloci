"use client";

import { ReactNode, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Brain,
  ChevronLeft,
  ChevronRight,
  FileText,
  Flame,
  Hash,
  Lightbulb,
  MessageSquare,
  Sparkles,
  Zap,
} from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

interface Props {
  totalMemories: number;
  totalKnacks: number;
  projectCount: number;
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: number | string;
}) {
  return (
    <Card className="pi-metric-card">
      <CardContent className="flex flex-col gap-2 p-0">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span className="flex size-6 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/10">
            <Icon className="size-3.5" />
          </span>
          {label}
        </span>
        <span className="text-3xl font-semibold tabular-nums leading-none tracking-[-0.04em]">{value}</span>
      </CardContent>
    </Card>
  );
}

function ActivityChart({ buckets }: { buckets: { date: string; count: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={64}>
      <AreaChart data={buckets} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="activity-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.4} />
            <stop offset="100%" stopColor="var(--primary)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="count"
          stroke="var(--primary)"
          strokeWidth={1.5}
          fill="url(#activity-grad)"
          isAnimationActive={false}
        />
        <Tooltip
          cursor={{ stroke: "var(--primary)", strokeWidth: 0.5, strokeDasharray: "3 3" }}
          content={(props) => {
            if (!props.active || !props.payload?.length) return null;
            const p = props.payload[0].payload as { date: string; count: number };
            return (
              <div className="rounded border bg-popover px-2 py-1 text-[11px] shadow-md">
                {p.date}: {p.count}
              </div>
            );
          }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function PanelCard({
  icon: Icon,
  title,
  children,
  footer,
}: {
  icon: typeof Activity;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="space-y-0 border-b px-4 py-3">
        <h3 className="inline-flex items-center gap-2 text-sm font-semibold">
          <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/10">
            <Icon className="size-4" />
          </span>
          {title}
        </h3>
      </CardHeader>
      <CardContent className="max-h-[320px] flex-1 overflow-y-auto p-3">{children}</CardContent>
      {footer && (
        <CardFooter className="justify-between border-t px-3 py-1.5">{footer}</CardFooter>
      )}
    </Card>
  );
}

function Pager({
  page,
  pageCount,
  onPrev,
  onNext,
}: {
  page: number;
  pageCount: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={onPrev}
          disabled={page === 0}
          aria-label="prev"
        >
          <ChevronLeft className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={onNext}
          disabled={page >= pageCount - 1}
          aria-label="next"
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
      <span className="text-[11px] tabular-nums text-muted-foreground">
        {page + 1} / {pageCount}
      </span>
    </>
  );
}

function usePager<T>(items: T[], pageSize: number) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const slice = items.slice(safePage * pageSize, safePage * pageSize + pageSize);
  return {
    page: safePage,
    pageCount,
    slice,
    onPrev: () => setPage((p) => Math.max(0, p - 1)),
    onNext: () => setPage((p) => Math.min(pageCount - 1, p + 1)),
  };
}

export function DashboardSummaryPanels({ totalMemories, totalKnacks, projectCount }: Props) {
  const { t, locale } = useTranslation();
  const summary = t.dashboard.summary;

  const { data, isLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: api.dashboardSummary,
  });

  const timeFmt = (iso: string) =>
    new Date(iso).toLocaleString(locale, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  const memories = data?.recent_memories ?? [];
  const instincts = data?.top_instincts ?? [];
  const tags = data?.top_tags ?? [];
  const sessions = data?.recent_sessions ?? [];

  const todayStr = new Date().toISOString().slice(0, 10);
  const todayCount = data?.activity?.find((b) => b.date === todayStr)?.count ?? 0;
  const weekCount = data?.activity?.slice(-7).reduce((s, b) => s + b.count, 0) ?? 0;
  const streak = (() => {
    if (!data?.activity) return 0;
    let s = 0;
    for (let i = data.activity.length - 1; i >= 0; i--) {
      if (data.activity[i].count > 0) s++;
      else break;
    }
    return s;
  })();
  const ANGER_KW = ['화', '화남', '분노', '짜증', '불만', '답답', '열받', '멘붕', '빡침', 'angry', 'frustrated', 'annoyed', 'upset'];
  const angryCount = data?.top_tags
    ?.filter((t) => ANGER_KW.some((k) => t.tag.toLowerCase().includes(k)))
    .reduce((s, t) => s + t.count, 0) ?? 0;

  const memPager = usePager(memories, 4);
  const instPager = usePager(instincts, 4);
  const tagPager = usePager(tags, 14);
  const sessPager = usePager(sessions, 5);

  return (
    <div className="mt-6 space-y-4">
      <div className="grid grid-cols-3 gap-3 lg:grid-cols-6">
        <StatCard icon={FileText} label={t.dashboard.stats.projects} value={projectCount} />
        <StatCard icon={Brain} label={t.dashboard.stats.totalMemories} value={totalMemories} />
        <StatCard icon={Lightbulb} label={t.dashboard.stats.totalKnacks} value={totalKnacks} />
        <Card className="col-span-3 flex flex-col">
          <CardHeader className="space-y-0 border-b px-4 py-3">
            <h3 className="inline-flex items-center gap-2 text-sm font-semibold">
              <span className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/10">
                <Activity className="size-4" />
              </span>
              {summary.activityTitle}
            </h3>
          </CardHeader>
          <CardContent className="flex-1 p-3">
            {isLoading ? (
              <Skeleton className="h-16 w-full" />
            ) : !data?.activity?.length ? (
              <p className="py-5 text-center text-xs text-muted-foreground">{summary.activityEmpty}</p>
            ) : (
              <ActivityChart buckets={data.activity} />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Fun stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { icon: MessageSquare, label: summary.funStats.today, value: isLoading ? "…" : String(todayCount), color: "text-blue-500", bg: "bg-blue-500/10" },
          { icon: Zap, label: summary.funStats.week, value: isLoading ? "…" : String(weekCount), color: "text-violet-500", bg: "bg-violet-500/10" },
          { icon: Flame, label: summary.funStats.streak, value: isLoading ? "…" : streak > 0 ? `${streak}${summary.funStats.streakUnit}` : "–", color: "text-orange-500", bg: "bg-orange-500/10" },
          { icon: Activity, label: summary.funStats.anger, value: isLoading ? "…" : angryCount > 0 ? `${angryCount}${summary.funStats.angerUnit}` : summary.funStats.angerNone, color: "text-rose-500", bg: "bg-rose-500/10" },
        ].map(({ icon: Icon, label, value, color, bg }) => (
          <div key={label} className="flex items-center gap-3 rounded-xl border bg-card/60 px-4 py-3">
            <span className={`flex size-8 shrink-0 items-center justify-center rounded-full ${bg}`}>
              <Icon className={`size-4 ${color}`} />
            </span>
            <div className="min-w-0">
              <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
              <p className="text-xl font-semibold tabular-nums leading-tight">{value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PanelCard
          icon={Brain}
          title={summary.recentMemoriesTitle}
          footer={
            memPager.pageCount > 1 ? (
              <Pager {...memPager} />
            ) : undefined
          }
        >
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : memories.length === 0 ? (
            <p className="py-8 text-center text-xs text-muted-foreground">
              {summary.recentMemoriesEmpty}
            </p>
          ) : (
            <ul className="space-y-2">
              {memPager.slice.map((m) => (
                <li key={m.memory_id}>
                  <Link
                    href={`/projects/?slug=${m.project_slug}`}
                    className="block rounded-lg border border-border/60 bg-card/50 px-3 py-2.5 transition-all hover:border-primary/40 hover:bg-accent/40 hover:shadow-sm"
                  >
                    <p className="line-clamp-2 break-words text-sm leading-snug">{m.content}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
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
        </PanelCard>

        <PanelCard
          icon={Lightbulb}
          title={summary.topKnacksTitle}
          footer={
            instPager.pageCount > 1 ? (
              <Pager {...instPager} />
            ) : undefined
          }
        >
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : instincts.length === 0 ? (
            <p className="py-8 text-center text-xs text-muted-foreground">
              {summary.topKnacksEmpty}
            </p>
          ) : (
            <ul className="space-y-2">
              {instPager.slice.map((i) => (
                <li
                  key={i.instinct_id}
                  className="rounded-lg border border-border/60 bg-card/50 px-3 py-2.5"
                >
                  <p className="line-clamp-1 break-words text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">when</span> {i.trigger}
                  </p>
                  <p className="mt-0.5 line-clamp-1 break-words text-sm">
                    <span className="font-medium text-primary">→</span> {i.action}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Badge variant="secondary" className="text-[10px]">
                      {i.project_slug}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                      {i.domain}
                    </Badge>
                    <span className="tabular-nums">×{i.instinct_count}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </PanelCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <PanelCard
          icon={Sparkles}
          title={summary.topTagsTitle}
          footer={
            tagPager.pageCount > 1 ? (
              <Pager {...tagPager} />
            ) : undefined
          }
        >
          {isLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : tags.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              {summary.topTagsEmpty}
            </p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {tagPager.slice.map((tag) => (
                <Badge key={tag.tag} variant="secondary" className="break-all">
                  #{tag.tag} <span className="ms-1 opacity-60 tabular-nums">×{tag.count}</span>
                </Badge>
              ))}
            </div>
          )}
        </PanelCard>

        <PanelCard
          icon={FileText}
          title={summary.recentSessionsTitle}
          footer={
            sessPager.pageCount > 1 ? (
              <Pager {...sessPager} />
            ) : undefined
          }
        >
          {isLoading ? (
            <div className="space-y-1.5">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">
              {summary.recentSessionsEmpty}
            </p>
          ) : (
            <ul className="divide-y divide-border/60">
              {sessPager.slice.map((s) => (
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
        </PanelCard>
      </div>
    </div>
  );
}
