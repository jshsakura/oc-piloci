"use client";

import { useId, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Brain,
  ChevronLeft,
  ChevronRight,
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
import { Button } from "@/components/ui/button";

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

function ActivityAreaChart({ buckets }: { buckets: { date: string; count: number }[] }) {
  const gradId = useId();
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const w = 100;
  const h = 32;
  const stepX = buckets.length > 1 ? w / (buckets.length - 1) : w;
  const points = buckets.map((b, i) => ({
    x: i * stepX,
    y: h - (b.count / max) * (h - 4) - 2,
    ...b,
  }));

  // Smooth path via Catmull-Rom → cubic Bezier conversion.
  const linePath = useMemo(() => {
    if (points.length === 0) return "";
    if (points.length === 1) return `M${points[0].x},${points[0].y}`;
    const segs: string[] = [`M${points[0].x},${points[0].y}`];
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i - 1] ?? points[i];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] ?? p2;
      const c1x = p1.x + (p2.x - p0.x) / 6;
      const c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6;
      const c2y = p2.y - (p3.y - p1.y) / 6;
      segs.push(`C${c1x},${c1y} ${c2x},${c2y} ${p2.x},${p2.y}`);
    }
    return segs.join(" ");
  }, [points]);

  const areaPath = `${linePath} L${w},${h} L0,${h} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-16 w-full">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" className="text-primary" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" className="text-primary" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path d={linePath} fill="none" stroke="currentColor" strokeWidth="0.6" className="text-primary" />
      {points.map((p) => (
        <circle key={p.date} cx={p.x} cy={p.y} r="0.9" className="fill-primary">
          <title>{`${p.date}: ${p.count}`}</title>
        </circle>
      ))}
    </svg>
  );
}

function CardFooter<T>({
  page,
  pageCount,
  onPrev,
  onNext,
}: {
  page: number;
  pageCount: number;
  items: T[];
  onPrev: () => void;
  onNext: () => void;
}) {
  if (pageCount <= 1) return null;
  return (
    <div className="mt-3 flex items-center justify-between border-t pt-2">
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
    </div>
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

  const memPager = usePager(memories, 4);
  const instPager = usePager(instincts, 4);
  const tagPager = usePager(tags, 12);
  const sessPager = usePager(sessions, 5);

  return (
    <div className="mt-6 space-y-4">
      {/* Compact stat strip + activity area chart */}
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
              <ActivityAreaChart buckets={data.activity} />
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Recent memories */}
        <Card>
          <CardContent className="p-3">
            <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold">
              <Brain className="size-4 text-primary" /> {summary.recentMemoriesTitle}
            </h3>
            {isLoading ? (
              <div className="space-y-1.5">
                {[1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : memories.length === 0 ? (
              <p className="py-6 text-center text-xs text-muted-foreground">
                {summary.recentMemoriesEmpty}
              </p>
            ) : (
              <>
                <ul className="space-y-1.5">
                  {memPager.slice.map((m) => (
                    <li key={m.memory_id}>
                      <Link
                        href={`/projects/?slug=${m.project_slug}`}
                        className="block min-w-0 rounded-md border bg-card px-2.5 py-1.5 transition-colors hover:bg-accent"
                      >
                        <p className="line-clamp-1 break-words text-sm">{m.content}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
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
                <CardFooter
                  page={memPager.page}
                  pageCount={memPager.pageCount}
                  items={memPager.slice}
                  onPrev={memPager.onPrev}
                  onNext={memPager.onNext}
                />
              </>
            )}
          </CardContent>
        </Card>

        {/* Top patterns */}
        <Card>
          <CardContent className="p-3">
            <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold">
              <Lightbulb className="size-4 text-primary" /> {summary.topKnacksTitle}
            </h3>
            {isLoading ? (
              <div className="space-y-1.5">
                {[1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : instincts.length === 0 ? (
              <p className="py-6 text-center text-xs text-muted-foreground">
                {summary.topKnacksEmpty}
              </p>
            ) : (
              <>
                <ul className="space-y-1.5">
                  {instPager.slice.map((i) => (
                    <li
                      key={i.instinct_id}
                      className="rounded-md border bg-card px-2.5 py-1.5"
                    >
                      <p className="line-clamp-1 break-words text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">when</span> {i.trigger}
                      </p>
                      <p className="line-clamp-1 break-words text-sm">
                        <span className="font-medium text-primary">→</span> {i.action}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                        <Badge variant="secondary" className="text-[10px]">
                          {i.project_slug}
                        </Badge>
                        <Badge variant="outline" className="text-[10px]">{i.domain}</Badge>
                        <span>×{i.instinct_count}</span>
                      </div>
                    </li>
                  ))}
                </ul>
                <CardFooter
                  page={instPager.page}
                  pageCount={instPager.pageCount}
                  items={instPager.slice}
                  onPrev={instPager.onPrev}
                  onNext={instPager.onNext}
                />
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Bottom row: tags + recent sessions, balanced 50:50 */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Top tags */}
        <Card>
          <CardContent className="p-3">
            <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="size-4 text-primary" /> {summary.topTagsTitle}
            </h3>
            {isLoading ? (
              <Skeleton className="h-20 w-full" />
            ) : tags.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                {summary.topTagsEmpty}
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {tagPager.slice.map((tag) => (
                    <Badge
                      key={tag.tag}
                      variant="secondary"
                      className="break-all"
                    >
                      #{tag.tag} <span className="ml-1 opacity-60">×{tag.count}</span>
                    </Badge>
                  ))}
                </div>
                <CardFooter
                  page={tagPager.page}
                  pageCount={tagPager.pageCount}
                  items={tagPager.slice}
                  onPrev={tagPager.onPrev}
                  onNext={tagPager.onNext}
                />
              </>
            )}
          </CardContent>
        </Card>

        {/* Recent sessions */}
        <Card>
          <CardContent className="p-3">
            <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold">
              <FileText className="size-4 text-primary" /> {summary.recentSessionsTitle}
            </h3>
            {isLoading ? (
              <div className="space-y-1.5">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-9 w-full" />
                ))}
              </div>
            ) : sessions.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted-foreground">
                {summary.recentSessionsEmpty}
              </p>
            ) : (
              <>
                <ul className="divide-y">
                  {sessPager.slice.map((s) => (
                    <li
                      key={s.ingest_id}
                      className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-xs"
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
                <CardFooter
                  page={sessPager.page}
                  pageCount={sessPager.pageCount}
                  items={sessPager.slice}
                  onPrev={sessPager.onPrev}
                  onNext={sessPager.onNext}
                />
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
