"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  Filter,
  Archive,
  Cpu,
  Activity,
  Moon,
  Play,
  XCircle,
  BrainCircuit,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/**
 * Distillation pipeline status panel for the dashboard.
 *
 * Surfaces the four observability dimensions the user agreed are needed for
 * lazy distillation to feel trustworthy: counts, lag, classification (filter
 * vs archive vs failed), freshness, plus the current scheduler signals
 * (temp, load, next idle window) and a manual trigger button.
 *
 * Polled every 15s — enough lag visibility without piling on requests.
 */
export function DistillationStatusPanel() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["distillationStatus"],
    queryFn: () => api.distillationStatus(),
    refetchInterval: 15_000,
    staleTime: 7_000,
  });

  const runNowMutation = useMutation({
    mutationFn: () => api.runDistillationNow(),
    onSuccess: () => {
      // Re-poll a couple times to surface the wake effect.
      setTimeout(
        () => queryClient.invalidateQueries({ queryKey: ["distillationStatus"] }),
        2_000,
      );
    },
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BrainCircuit className="size-4 text-muted-foreground" />
            기억 정리 현황
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">로딩 중…</CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BrainCircuit className="size-4 text-muted-foreground" />
            기억 정리 현황
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-destructive">상태 조회 실패</CardContent>
      </Card>
    );
  }

  const { counts, lag, last_distilled_at, processing_path_30d, current, schedule, thresholds } =
    data;

  const lagHours = lag.seconds_behind ? lag.seconds_behind / 3600 : 0;
  const isHealthy = counts.pending === 0 || lagHours < 1;
  const isOverflow = counts.pending >= thresholds.overflow_threshold;
  const localCount = processing_path_30d.local ?? 0;
  const externalCount = processing_path_30d.external ?? 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <BrainCircuit className="size-4 text-muted-foreground" />
          기억 정리 현황
        </CardTitle>
        <Button
          size="sm"
          variant="outline"
          onClick={() => runNowMutation.mutate()}
          disabled={runNowMutation.isPending || counts.pending === 0}
          className="h-8 gap-1"
        >
          <Play className="size-3" />
          지금 실행
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          {isHealthy ? (
            <Badge variant="outline" className="gap-1 border-emerald-500 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="size-3" /> 최신
            </Badge>
          ) : isOverflow ? (
            <Badge variant="outline" className="gap-1 border-amber-500 text-amber-600 dark:text-amber-400">
              <AlertTriangle className="size-3" /> {Math.round(lagHours)}h 지연
            </Badge>
          ) : (
            <Badge variant="outline" className="gap-1">
              <Clock className="size-3" /> 대기 {counts.pending}
            </Badge>
          )}
          {!data.enabled && (
            <Badge variant="outline" className="gap-1 border-muted text-muted-foreground">
              비활성화됨
            </Badge>
          )}
        </div>

        {/* State counts */}
        <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-5">
          <CountCell
            icon={<Clock className="size-4" />}
            label="대기"
            value={counts.pending}
            tone={counts.pending > 0 ? "warn" : "muted"}
          />
          <CountCell
            icon={<CheckCircle2 className="size-4" />}
            label="증류됨"
            value={counts.distilled}
            tone="ok"
          />
          <CountCell
            icon={<Filter className="size-4" />}
            label="필터됨"
            value={counts.filtered}
            tone="muted"
          />
          <CountCell
            icon={<XCircle className="size-4" />}
            label="실패"
            value={counts.failed}
            tone={counts.failed > 0 ? "warn" : "muted"}
          />
          <CountCell
            icon={<Archive className="size-4" />}
            label="아카이브"
            value={counts.archived}
            tone="muted"
          />
        </div>

        {/* Processing path split */}
        {(localCount > 0 || externalCount > 0) && (
          <div className="border-t pt-3">
            <div className="mb-2 text-xs text-muted-foreground">최근 30일 처리 경로</div>
            <div className="flex gap-2 text-sm">
              <Badge variant="outline">로컬 {localCount}</Badge>
              {externalCount > 0 && <Badge variant="outline">외부 {externalCount}</Badge>}
            </div>
          </div>
        )}

        {/* Current signals + schedule */}
        <div className="grid grid-cols-2 gap-3 border-t pt-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Cpu className="size-3" />
            온도{" "}
            {current.cpu_temp_c !== null
              ? `${current.cpu_temp_c.toFixed(1)}°C`
              : "—"}{" "}
            / {thresholds.temp_ceiling_c.toFixed(0)}°C
          </div>
          <div className="flex items-center gap-1">
            <Activity className="size-3" />
            부하{" "}
            {current.load_avg_1m !== null
              ? current.load_avg_1m.toFixed(2)
              : "—"}{" "}
            / {thresholds.load_ceiling_1m.toFixed(1)}
          </div>
          <div className="flex items-center gap-1">
            <Moon className="size-3" />
            야간 모드 {schedule.idle_window || "꺼짐"}
          </div>
          <div className="flex items-center gap-1">
            <Clock className="size-3" />
            마지막 증류{" "}
            {last_distilled_at
              ? new Date(last_distilled_at).toLocaleString("ko-KR", {
                  hour: "2-digit",
                  minute: "2-digit",
                  month: "short",
                  day: "numeric",
                })
              : "없음"}
          </div>
        </div>

        {runNowMutation.isSuccess && (
          <p className="text-xs text-muted-foreground">
            워커에 즉시 실행 신호 보냄. 온도·부하 게이트는 그대로 적용됩니다.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function CountCell({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: "ok" | "warn" | "muted";
}) {
  const toneClass =
    tone === "ok"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "warn"
      ? "text-amber-600 dark:text-amber-400"
      : "text-muted-foreground";
  return (
    <div className="flex flex-col gap-0.5 rounded-md border p-2">
      <div className={`flex items-center gap-1 text-xs ${toneClass}`}>
        {icon}
        <span>{label}</span>
      </div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
