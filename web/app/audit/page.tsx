"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/auth";
import { api } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import AppShell from "@/components/AppShell";
import { useTranslation } from "@/lib/i18n";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const LIMIT = 20;

// Order = how the filter dropdown shows entries. Keys must mirror the action
// strings the backend writes to audit_logs.action. Labels are resolved at
// render time via t.audit.actions[<key>].
const ACTION_KEYS = [
  "all",
  "signup",
  "login_success",
  "login_fail",
  "login_fail_totp",
  "password_reset",
  "token_created",
  "token_revoked",
  "project_created",
  "project_deleted",
  "admin_toggle_admin",
  "admin_toggle_active",
  "admin_delete_user",
] as const;

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
  const { t } = useTranslation();
  // Falls back to the raw action string if the backend emits an action we
  // haven't translated yet — surfaces the gap instead of silently dropping it.
  const labels = t.audit.actions as Record<string, string | undefined>;
  const label = labels[action] ?? action;

  const isSuccess = action.includes("success") || action.includes("created") || action === "signup";
  const isFail = action.includes("fail") || action.includes("deleted") || action.includes("revoked");

  if (isSuccess) return <Badge variant="default" className="text-xs">{label}</Badge>;
  if (isFail) return <Badge variant="destructive" className="text-xs">{label}</Badge>;
  return <Badge variant="secondary" className="text-xs">{label}</Badge>;
}

export default function AuditPage() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();
  const [actionFilter, setActionFilter] = useState("all");
  const [offset, setOffset] = useState(0);

  const actionParam = actionFilter === "all" ? undefined : actionFilter;

  const { data: logs, isLoading, isError } = useQuery<AuditLog[]>({
    queryKey: ["audit", actionFilter, offset],
    queryFn: () => api.listAudit(LIMIT, offset, actionParam),
    enabled: !!user,
  });

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) router.replace("/login");
  }, [hasHydrated, isBootstrapping, user, router]);

  if (!hasHydrated || isBootstrapping) {
    return (
      <AppShell>
        <RoutePending title={t.audit.pending.title} description={t.audit.pending.desc} />
      </AppShell>
    );
  }

  if (!user) {
    return (
      <RoutePending
        fullScreen
        title={t.audit.redirect.title}
        description={t.audit.redirect.desc}
      />
    );
  }

  const hasPrev = offset > 0;
  const hasNext = (logs?.length ?? 0) === LIMIT;

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">{t.audit.title}</h1>
          <p className="text-sm text-muted-foreground">{t.audit.subtitle}</p>
        </div>

        <Card className="bg-card shadow-sm">
          <CardContent className="flex flex-col gap-4 pt-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium">{t.audit.filter}</p>
              <p className="text-xs text-muted-foreground">{t.audit.subtitle}</p>
            </div>
            <div className="w-full sm:w-56">
              <Select value={actionFilter} onValueChange={(v) => { setActionFilter(v); setOffset(0); }}>
                <SelectTrigger className="bg-card"><SelectValue placeholder={t.audit.filter} /></SelectTrigger>
                <SelectContent>
                  {ACTION_KEYS.map((key) => {
                    const labels = t.audit.actions as Record<string, string | undefined>;
                    return (
                      <SelectItem key={key} value={key}>
                        {labels[key] ?? key}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3 md:hidden">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="bg-card shadow-sm">
                <CardContent className="space-y-3 pt-6">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-5 w-20" />
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 w-36" />
                </CardContent>
              </Card>
            ))
          ) : isError ? (
            <Card className="bg-card shadow-sm">
              <CardContent className="py-12 text-center text-muted-foreground">{t.audit.empty.error}</CardContent>
            </Card>
          ) : !logs || logs.length === 0 ? (
            <Card className="bg-card shadow-sm">
              <CardContent className="py-12 text-center text-muted-foreground">{t.audit.empty.noLogs}</CardContent>
            </Card>
          ) : (
            logs.map((log) => (
              <Card key={log.id} className="bg-card shadow-sm">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-sm font-medium">{formatKST(log.created_at)}</CardTitle>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">{log.ip_address ?? "-"}</p>
                    </div>
                    <ActionBadge action={log.action} />
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-xs text-muted-foreground break-all">{log.user_agent || "-"}</p>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        <Card className="hidden overflow-hidden bg-card shadow-sm md:block">
          <Table>
            <TableHeader className="bg-muted/50">
              <TableRow>
                <TableHead>{t.audit.table.time}</TableHead>
                <TableHead>{t.audit.table.event}</TableHead>
                <TableHead>{t.audit.table.ip}</TableHead>
                <TableHead>{t.audit.table.userAgent}</TableHead>
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
                    {t.audit.empty.error}
                  </TableCell>
                </TableRow>
              ) : !logs || logs.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-12 text-center text-muted-foreground">
                    {t.audit.empty.noLogs}
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
        </Card>

        {!isLoading && !isError && (hasPrev || hasNext) && (
          <div className="flex items-center justify-end gap-3">
            <span className="text-sm text-muted-foreground">{t.audit.pagination.page} {offset / LIMIT + 1}</span>
            <Button variant="outline" size="sm" disabled={!hasPrev} onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}>
              {t.audit.pagination.prev}
            </Button>
            <Button variant="outline" size="sm" disabled={!hasNext} onClick={() => setOffset((o) => o + LIMIT)}>
              {t.audit.pagination.next}
            </Button>
          </div>
        )}
      </div>
    </AppShell>
  );
}
