"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/auth";
import { api } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import RoutePending from "@/components/RoutePending";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent } from "@/components/ui/card";

const LIMIT = 20;

const ACTION_OPTIONS = [
  { value: "all", label: "전체" },
  { value: "login_success", label: "로그인 성공" },
  { value: "login_fail", label: "로그인 실패" },
  { value: "signup", label: "회원가입" },
  { value: "token_created", label: "토큰 생성" },
  { value: "token_revoked", label: "토큰 폐기" },
  { value: "project_created", label: "프로젝트 생성" },
  { value: "project_deleted", label: "프로젝트 삭제" },
];

function formatKST(isoString: string): string {
  try {
    return new Date(isoString).toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return isoString;
  }
}

function ActionBadge({ action }: { action: string }) {
  const isSuccess = action.includes("success") || action.includes("created") || action === "signup";
  const isFail = action.includes("fail") || action.includes("deleted") || action.includes("revoked");

  if (isSuccess) return <Badge variant="default" className="text-xs">{action}</Badge>;
  if (isFail) return <Badge variant="destructive" className="text-xs">{action}</Badge>;
  return <Badge variant="secondary" className="text-xs">{action}</Badge>;
}

export default function AuditPage() {
  const router = useRouter();
  const { user, hasHydrated } = useAuthStore();
  const [actionFilter, setActionFilter] = useState("all");
  const [offset, setOffset] = useState(0);

  const actionParam = actionFilter === "all" ? undefined : actionFilter;

  const { data: logs, isLoading, isError } = useQuery<AuditLog[]>({
    queryKey: ["audit", actionFilter, offset],
    queryFn: () => api.listAudit(LIMIT, offset, actionParam),
    enabled: !!user,
  });

  useEffect(() => {
    if (hasHydrated && !user) router.replace("/login");
  }, [hasHydrated, user, router]);

  if (!hasHydrated) {
    return (
      <AppShell>
        <RoutePending title="감사 로그 준비 중" description="로그인 상태와 필터 설정을 복원한 뒤 감사 로그를 표시합니다." />
      </AppShell>
    );
  }

  if (!user) {
    return (
      <RoutePending
        fullScreen
        title="로그인 화면으로 이동 중"
        description="감사 로그는 보호된 화면이라 로그인 페이지로 이동합니다."
      />
    );
  }

  const hasPrev = offset > 0;
  const hasNext = (logs?.length ?? 0) === LIMIT;

  return (
    <AppShell>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">감사 로그</h1>
          <p className="text-sm text-muted-foreground">보안 이벤트 및 접근 기록</p>
        </div>
        <div className="w-full sm:w-48">
          <Select value={actionFilter} onValueChange={(v) => { setActionFilter(v); setOffset(0); }}>
            <SelectTrigger><SelectValue placeholder="필터" /></SelectTrigger>
            <SelectContent>
              {ACTION_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-6 rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>시간</TableHead>
              <TableHead>이벤트</TableHead>
              <TableHead>IP</TableHead>
              <TableHead>User Agent</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell><Skeleton className="h-4 w-32" /></TableCell>
                  <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                  <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                  <TableCell><Skeleton className="h-4 w-36" /></TableCell>
                </TableRow>
              ))
            ) : isError ? (
              <TableRow>
                <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
                  감사 로그를 불러오지 못했습니다
                </TableCell>
              </TableRow>
            ) : !logs || logs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
                  기록된 이벤트가 없습니다
                </TableCell>
              </TableRow>
            ) : (
              logs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                    {formatKST(log.created_at)}
                  </TableCell>
                  <TableCell><ActionBadge action={log.action} /></TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{log.ip_address ?? "-"}</TableCell>
                  <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">
                    {log.user_agent ? log.user_agent.slice(0, 40) : "-"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {!isLoading && !isError && (hasPrev || hasNext) && (
        <div className="mt-4 flex items-center justify-end gap-3">
          <span className="text-sm text-muted-foreground">페이지 {offset / LIMIT + 1}</span>
          <Button variant="outline" size="sm" disabled={!hasPrev} onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}>
            이전
          </Button>
          <Button variant="outline" size="sm" disabled={!hasNext} onClick={() => setOffset((o) => o + LIMIT)}>
            다음
          </Button>
        </div>
      )}
    </AppShell>
  );
}
