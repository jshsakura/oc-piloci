"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Distillation preferences editor.
 *
 * Each field is optional: an empty input clears the preference, which makes
 * the user inherit the server-wide default. Validation matches the backend's
 * PATCH /api/preferences guards so we surface errors instantly without a
 * round-trip.
 *
 * Lives in the settings page under its own "증류" tab so it's discoverable
 * without crowding the existing account/security controls.
 */
export function DistillationSettingsPanel() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["distillationPreferences"],
    queryFn: () => api.getDistillationPreferences(),
  });

  const [idleWindow, setIdleWindow] = useState("");
  const [tempCeiling, setTempCeiling] = useState("");
  const [loadCeiling, setLoadCeiling] = useState("");
  const [overflow, setOverflow] = useState("");
  const [budget, setBudget] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    setIdleWindow(data.distillation_idle_window ?? "");
    setTempCeiling(
      data.distillation_temp_ceiling_c !== null
        ? String(data.distillation_temp_ceiling_c)
        : "",
    );
    setLoadCeiling(
      data.distillation_load_ceiling_1m !== null
        ? String(data.distillation_load_ceiling_1m)
        : "",
    );
    setOverflow(
      data.distillation_overflow_threshold !== null
        ? String(data.distillation_overflow_threshold)
        : "",
    );
    setBudget(
      data.external_budget_monthly_usd !== null
        ? String(data.external_budget_monthly_usd)
        : "",
    );
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: (
      body: Partial<import("@/lib/types").DistillationPreferences>,
    ) => api.updateDistillationPreferences(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["distillationPreferences"] });
      queryClient.invalidateQueries({ queryKey: ["distillationStatus"] });
      setError(null);
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "저장 실패");
    },
  });

  const onSave = () => {
    setError(null);
    const body: Partial<import("@/lib/types").DistillationPreferences> = {};

    body.distillation_idle_window = idleWindow.trim() === "" ? null : idleWindow.trim();
    if (
      body.distillation_idle_window !== null &&
      !/^\d{1,2}:\d{2}-\d{1,2}:\d{2}$/.test(body.distillation_idle_window)
    ) {
      setError("야간 윈도는 HH:MM-HH:MM 형식이어야 합니다.");
      return;
    }

    if (tempCeiling.trim() === "") {
      body.distillation_temp_ceiling_c = null;
    } else {
      const v = Number(tempCeiling);
      if (!Number.isFinite(v) || v <= 0 || v >= 100) {
        setError("온도 천장은 0~100°C 범위여야 합니다.");
        return;
      }
      body.distillation_temp_ceiling_c = v;
    }

    if (loadCeiling.trim() === "") {
      body.distillation_load_ceiling_1m = null;
    } else {
      const v = Number(loadCeiling);
      if (!Number.isFinite(v) || v <= 0 || v >= 64) {
        setError("로드 천장은 0~64 범위여야 합니다.");
        return;
      }
      body.distillation_load_ceiling_1m = v;
    }

    if (overflow.trim() === "") {
      body.distillation_overflow_threshold = null;
    } else {
      const v = Number(overflow);
      if (!Number.isInteger(v) || v < 0) {
        setError("오버플로 임계값은 0 이상의 정수여야 합니다.");
        return;
      }
      body.distillation_overflow_threshold = v;
    }

    if (budget.trim() === "") {
      body.external_budget_monthly_usd = null;
    } else {
      const v = Number(budget);
      if (!Number.isFinite(v) || v < 0) {
        setError("월 예산은 0 이상이어야 합니다.");
        return;
      }
      body.external_budget_monthly_usd = v;
    }

    saveMutation.mutate(body);
  };

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">증류 설정</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">로딩 중…</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">증류 설정</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-muted-foreground">
          빈 값으로 두면 서버 기본값을 따릅니다. 값을 입력하면 이 사용자에 한해 덮어씁니다.
        </p>

        <div className="space-y-2">
          <Label htmlFor="idle-window">야간 모드 시간 (HH:MM-HH:MM)</Label>
          <Input
            id="idle-window"
            value={idleWindow}
            onChange={(e) => setIdleWindow(e.target.value)}
            placeholder="예: 02:00-07:00"
          />
          <p className="text-xs text-muted-foreground">
            이 시간대에는 온도/부하 무시하고 적극적으로 백로그를 처리합니다.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="temp-ceiling">온도 천장 (°C)</Label>
            <Input
              id="temp-ceiling"
              type="number"
              step="0.5"
              value={tempCeiling}
              onChange={(e) => setTempCeiling(e.target.value)}
              placeholder="기본값"
            />
            <p className="text-xs text-muted-foreground">
              주간 시간대 SoC 온도가 이 값을 넘으면 워커가 멈춥니다.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="load-ceiling">부하 천장 (1분)</Label>
            <Input
              id="load-ceiling"
              type="number"
              step="0.1"
              value={loadCeiling}
              onChange={(e) => setLoadCeiling(e.target.value)}
              placeholder="기본값"
            />
            <p className="text-xs text-muted-foreground">
              load avg가 이 값을 넘으면 워커가 멈춥니다.
            </p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="overflow">오버플로 임계값 (대기 행 수)</Label>
            <Input
              id="overflow"
              type="number"
              step="1"
              value={overflow}
              onChange={(e) => setOverflow(e.target.value)}
              placeholder="기본값"
            />
            <p className="text-xs text-muted-foreground">
              대기 행이 이 수를 넘으면 외부 LLM으로 우회합니다 (외부 키 + 예산이 있을 때).
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="budget">월 외부 LLM 예산 (USD)</Label>
            <Input
              id="budget"
              type="number"
              step="0.01"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="제한 없음"
            />
            <p className="text-xs text-muted-foreground">
              비워두면 무제한. 값이 있고 한도를 넘으면 외부 우회를 차단합니다.
            </p>
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}
        {saveMutation.isSuccess && (
          <p className="text-sm text-emerald-600 dark:text-emerald-400">저장됨.</p>
        )}

        <div className="flex justify-end">
          <Button onClick={onSave} disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "저장 중…" : "저장"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
