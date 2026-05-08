"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Brain,
  ChevronLeft,
  ChevronRight,
  FileText,
  Hash,
  Lightbulb,
  Sparkles,
} from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";
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

type Memory = {
  memory_id: string;
  content: string;
  tags: string[];
  project_slug: string;
  project_name: string;
  created_at: number;
  updated_at: number;
};

type Instinct = {
  instinct_id: string;
  trigger: string;
  action: string;
  domain: string;
  confidence: number;
  instinct_count: number;
  project_slug: string;
  project_name: string;
};

type Session = {
  ingest_id: string;
  project_slug?: string | null;
  project_name?: string | null;
  created_at: string;
  processed_at?: string | null;
  memories_extracted: number;
  client: string;
};

type TagRow = { tag: string; count: number };

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

function DataTableCard<T>({
  title,
  icon: Icon,
  columns,
  data,
  emptyText,
  pageSize,
  isLoading,
}: {
  title: string;
  icon: typeof Activity;
  columns: ColumnDef<T, unknown>[];
  data: T[];
  emptyText: string;
  pageSize: number;
  isLoading: boolean;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
  });

  const pageIndex = table.getState().pagination.pageIndex;
  const pageCount = table.getPageCount();

  return (
    <Card>
      <CardContent className="p-3">
        <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold">
          <Icon className="size-4 text-primary" /> {title}
        </h3>
        {isLoading ? (
          <div className="space-y-1.5">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : data.length === 0 ? (
          <p className="py-6 text-center text-xs text-muted-foreground">{emptyText}</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <thead>
                  {table.getHeaderGroups().map((hg) => (
                    <tr key={hg.id} className="border-b text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {hg.headers.map((h) => {
                        const sorted = h.column.getIsSorted();
                        const canSort = h.column.getCanSort();
                        return (
                          <th key={h.id} className="px-2 py-1.5 text-left">
                            {h.isPlaceholder ? null : canSort ? (
                              <button
                                type="button"
                                onClick={h.column.getToggleSortingHandler()}
                                className="inline-flex items-center gap-1 hover:text-foreground"
                              >
                                {flexRender(h.column.columnDef.header, h.getContext())}
                                {sorted === "asc" ? (
                                  <ArrowUp className="size-3" />
                                ) : sorted === "desc" ? (
                                  <ArrowDown className="size-3" />
                                ) : (
                                  <ArrowUpDown className="size-3 opacity-40" />
                                )}
                              </button>
                            ) : (
                              flexRender(h.column.columnDef.header, h.getContext())
                            )}
                          </th>
                        );
                      })}
                    </tr>
                  ))}
                </thead>
                <tbody>
                  {table.getRowModel().rows.map((row) => (
                    <tr
                      key={row.id}
                      className="border-b border-muted/40 transition-colors last:border-b-0 hover:bg-accent/50"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-2 py-1.5 align-middle">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pageCount > 1 && (
              <div className="mt-2 flex items-center justify-between border-t pt-2">
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    onClick={() => table.previousPage()}
                    disabled={!table.getCanPreviousPage()}
                    aria-label="prev"
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    onClick={() => table.nextPage()}
                    disabled={!table.getCanNextPage()}
                    aria-label="next"
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  {pageIndex + 1} / {pageCount}
                </span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function DashboardSummaryPanels({ totalMemories, totalKnacks, projectCount }: Props) {
  const { t, locale } = useTranslation();
  const summary = t.dashboard.summary;
  const cols = summary.cols;

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

  const memoryColumns: ColumnDef<Memory, unknown>[] = [
    {
      accessorKey: "content",
      header: cols.memory,
      cell: ({ row }) => (
        <Link
          href={`/projects/?slug=${row.original.project_slug}`}
          className="line-clamp-1 break-words hover:underline"
        >
          {row.original.content}
        </Link>
      ),
    },
    {
      accessorKey: "project_slug",
      header: cols.project,
      cell: ({ row }) => (
        <Badge variant="secondary" className="text-[10px]">
          {row.original.project_slug}
        </Badge>
      ),
    },
    {
      id: "tags",
      header: cols.tags,
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1 text-[11px] text-muted-foreground">
          {row.original.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="inline-flex items-center gap-0.5">
              <Hash className="size-2.5" />
              {tag}
            </span>
          ))}
        </div>
      ),
    },
  ];

  const instinctColumns: ColumnDef<Instinct, unknown>[] = [
    {
      accessorKey: "trigger",
      header: cols.when,
      cell: ({ row }) => (
        <span className="line-clamp-1 break-words text-muted-foreground">{row.original.trigger}</span>
      ),
    },
    {
      accessorKey: "action",
      header: cols.then,
      cell: ({ row }) => (
        <span className="line-clamp-1 break-words">{row.original.action}</span>
      ),
    },
    {
      accessorKey: "project_slug",
      header: cols.project,
      cell: ({ row }) => (
        <Badge variant="secondary" className="text-[10px]">
          {row.original.project_slug}
        </Badge>
      ),
    },
    {
      accessorKey: "domain",
      header: cols.domain,
      cell: ({ row }) => (
        <Badge variant="outline" className="text-[10px]">
          {row.original.domain}
        </Badge>
      ),
    },
    {
      accessorKey: "instinct_count",
      header: cols.count,
      cell: ({ row }) => <span className="tabular-nums">×{row.original.instinct_count}</span>,
    },
  ];

  const tagColumns: ColumnDef<TagRow, unknown>[] = [
    {
      accessorKey: "tag",
      header: cols.tag,
      cell: ({ row }) => (
        <span className="inline-flex items-center gap-0.5">
          <Hash className="size-2.5 text-muted-foreground" />
          {row.original.tag}
        </span>
      ),
    },
    {
      accessorKey: "count",
      header: cols.count,
      cell: ({ row }) => <span className="tabular-nums">×{row.original.count}</span>,
    },
  ];

  const sessionColumns: ColumnDef<Session, unknown>[] = [
    {
      accessorKey: "project_name",
      header: cols.project,
      cell: ({ row }) =>
        row.original.project_slug ? (
          <Link
            href={`/projects/?slug=${row.original.project_slug}`}
            className="font-medium hover:underline"
          >
            {row.original.project_name}
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      id: "status",
      header: cols.status,
      enableSorting: false,
      cell: ({ row }) => (
        <span className="text-muted-foreground">
          {row.original.processed_at
            ? summary.sessionMemories.replace(
                "{count}",
                String(row.original.memories_extracted),
              )
            : summary.sessionPending}
        </span>
      ),
    },
    {
      accessorKey: "created_at",
      header: cols.time,
      cell: ({ row }) => (
        <span className="text-muted-foreground">{timeFmt(row.original.created_at)}</span>
      ),
    },
  ];

  const memories = data?.recent_memories ?? [];
  const instincts = data?.top_instincts ?? [];
  const tags = data?.top_tags ?? [];
  const sessions = data?.recent_sessions ?? [];

  return (
    <div className="mt-6 space-y-4">
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
              <ActivityChart buckets={data.activity} />
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <DataTableCard<Memory>
          title={summary.recentMemoriesTitle}
          icon={Brain}
          columns={memoryColumns}
          data={memories}
          emptyText={summary.recentMemoriesEmpty}
          pageSize={5}
          isLoading={isLoading}
        />
        <DataTableCard<Instinct>
          title={summary.topKnacksTitle}
          icon={Lightbulb}
          columns={instinctColumns}
          data={instincts}
          emptyText={summary.topKnacksEmpty}
          pageSize={5}
          isLoading={isLoading}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <DataTableCard<TagRow>
          title={summary.topTagsTitle}
          icon={Sparkles}
          columns={tagColumns}
          data={tags}
          emptyText={summary.topTagsEmpty}
          pageSize={8}
          isLoading={isLoading}
        />
        <DataTableCard<Session>
          title={summary.recentSessionsTitle}
          icon={FileText}
          columns={sessionColumns}
          data={sessions}
          emptyText={summary.recentSessionsEmpty}
          pageSize={6}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
}
