"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  CheckCircle2,
  XCircle,
  Clock,
  ShieldCheck,
  ShieldOff,
  ToggleLeft,
  ToggleRight,
  Trash2,
  Search,
  MoreHorizontal,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { AdminUser } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import RoutePending from "@/components/RoutePending";

type StatusFilter = "all" | "pending" | "approved" | "rejected" | "inactive";

export default function AdminUsersPage() {
  const router = useRouter();
  const { user: me, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [rejectTarget, setRejectTarget] = useState<AdminUser | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; message: string } | null>(null);

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && (!me || !me.is_admin)) {
      router.replace("/dashboard");
    }
  }, [hasHydrated, isBootstrapping, me, router]);

  const fetchUsers = async (status?: string) => {
    setLoading(true);
    setError(false);
    try {
      const result = await api.adminListUsers(status);
      setUsers(result as AdminUser[]);
    } catch {
      setUsers([]);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (me?.is_admin) {
      const apiStatus = filter === "all" || filter === "inactive" ? undefined : filter;
      void fetchUsers(apiStatus);
    }
  }, [filter, me?.is_admin]);

  const filtered = useMemo(() => {
    let list = users;
    if (filter === "inactive") list = list.filter((u) => !u.is_active);
    if (!search.trim()) return list;
    const q = search.toLowerCase();
    return list.filter(
      (u) => u.email.toLowerCase().includes(q) || (u.name && u.name.toLowerCase().includes(q))
    );
  }, [users, search, filter]);

  const stats = useMemo(() => {
    const total = users.length;
    const pending = users.filter((u) => u.approval_status === "pending").length;
    const admins = users.filter((u) => u.is_admin).length;
    return { total, pending, admins };
  }, [users]);

  if (!hasHydrated || isBootstrapping || !me) return <AppShell><RoutePending title={t.admin.title} description={t.admin.description} /></AppShell>;
  if (!me.is_admin) return <AppShell><RoutePending title={t.admin.title} description={t.admin.description} fullScreen /></AppShell>;

  const isSelf = (id: string) => me.user_id === id;

  // Replace {email} in a toast template with the actual address.
  const fillEmail = (template: string, email: string) => template.replace("{email}", email);

  const handleAction = async (fn: () => Promise<unknown>, successMsg?: string) => {
    setActionPending(true);
    setFeedback(null);
    try {
      await fn();
      if (successMsg) setFeedback({ type: "ok", message: successMsg });
      void fetchUsers(filter === "all" ? undefined : filter);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Error";
      setFeedback({ type: "err", message: msg });
    } finally {
      setActionPending(false);
    }
  };

  const filters: { key: StatusFilter; label: string }[] = [
    { key: "all", label: t.admin.filterAll },
    { key: "pending", label: t.admin.filterPending },
    { key: "approved", label: t.admin.filterApproved },
    { key: "rejected", label: t.admin.filterRejected },
    { key: "inactive", label: t.admin.filterInactive },
  ];

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
      approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
      rejected: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    };
    return (
      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? ""}`}>
        {status === "pending" && <Clock className="h-3 w-3" />}
        {status === "approved" && <CheckCircle2 className="h-3 w-3" />}
        {status === "rejected" && <XCircle className="h-3 w-3" />}
        {t.admin.status[status as keyof typeof t.admin.status] ?? status}
      </span>
    );
  };

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">{t.admin.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t.admin.description}</p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { label: t.admin.statsTotal, value: stats.total, icon: Users, color: "text-foreground" },
            { label: t.admin.statsPending, value: stats.pending, icon: Clock, color: "text-amber-600 dark:text-amber-400" },
            { label: t.admin.statsAdmins, value: stats.admins, icon: ShieldCheck, color: "text-primary" },
          ].map((s) => (
            <div key={s.label} className="flex items-center gap-3 rounded-lg border bg-card p-4 shadow-sm">
              <div className={`flex h-9 w-9 items-center justify-center rounded-lg bg-muted ${s.color}`}>
                <s.icon className="h-4 w-4" />
              </div>
              <div>
                <p className="text-2xl font-bold leading-none">{s.value}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{s.label}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-1 overflow-x-auto pb-1 sm:flex-wrap sm:pb-0">
            {filters.map((f) => (
              <Button
                key={f.key}
                variant={filter === f.key ? "secondary" : "ghost"}
                size="sm"
                className="shrink-0"
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </Button>
            ))}
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t.admin.searchPlaceholder}
              className="h-8 w-full rounded-md border border-input bg-background pl-8 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring sm:w-56"
            />
          </div>
        </div>

        {feedback && (
          <div
            className={`rounded-md border px-4 py-2.5 text-sm shadow-sm ${
              feedback.type === "ok"
                ? "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                : "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
            }`}
          >
            {feedback.message}
          </div>
        )}

        {loading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            <p className="text-sm text-muted-foreground">{t.common.loading}</p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16">
            <p className="text-sm text-muted-foreground">{t.admin.loadError}</p>
            <Button variant="outline" size="sm" onClick={() => void fetchUsers(filter === "all" ? undefined : filter)}>
              {t.admin.retry}
            </Button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed bg-card py-16">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <Users className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm font-medium text-muted-foreground">{t.admin.emptyMessage}</p>
          </div>
        ) : (
          <>
            <div className="space-y-3 md:hidden">
              {filtered.map((u) => (
                <div key={u.id} className="rounded-lg border bg-card p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-medium">
                        {(u.email?.charAt(0) ?? "?").toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1">
                          <span className="truncate font-medium text-sm">{u.email}</span>
                          {u.is_admin && (
                            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                              {t.admin.adminBadge}
                            </span>
                          )}
                          {!u.is_active && (
                            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
                              {t.admin.inactiveBadge}
                            </span>
                          )}
                          {isSelf(u.id) && (
                            <span className="text-[10px] text-muted-foreground">{t.admin.you}</span>
                          )}
                        </div>
                        {u.name && <div className="text-xs text-muted-foreground">{u.name}</div>}
                      </div>
                    </div>
                    {statusBadge(u.approval_status)}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    {u.created_at && (
                      <span>{new Date(u.created_at).toLocaleDateString()}</span>
                    )}
                    {u.oauth_provider && <span>{u.oauth_provider}</span>}
                    {u.totp_enabled && <span>2FA</span>}
                  </div>
                  <div className="mt-3 border-t pt-3">
                    {u.approval_status === "pending" ? (
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          className="flex-1"
                          onClick={() => void handleAction(() => api.adminApproveUser(u.id), fillEmail(t.admin.toastApproved, u.email))}
                          disabled={actionPending}
                        >
                          {t.admin.approve}
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="flex-1"
                          onClick={() => setRejectTarget(u)}
                          disabled={actionPending}
                        >
                          {t.admin.reject}
                        </Button>
                      </div>
                    ) : (
                      !isSelf(u.id) && (
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            className="flex-1"
                            onClick={() => void handleAction(
                              () => api.adminToggleAdmin(u.id),
                              fillEmail(u.is_admin ? t.admin.toastDemoted : t.admin.toastPromoted, u.email),
                            )}
                            disabled={actionPending}
                          >
                            {u.is_admin ? (
                              <><ShieldOff className="mr-1.5 h-3.5 w-3.5" />{t.admin.demoteAdmin}</>
                            ) : (
                              <><ShieldCheck className="mr-1.5 h-3.5 w-3.5" />{t.admin.promoteAdmin}</>
                            )}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="flex-1"
                            onClick={() => void handleAction(
                              () => api.adminToggleActive(u.id),
                              fillEmail(u.is_active ? t.admin.toastDeactivated : t.admin.toastActivated, u.email),
                            )}
                            disabled={actionPending}
                          >
                            {u.is_active ? (
                              <><ToggleLeft className="mr-1.5 h-3.5 w-3.5" />{t.admin.deactivateUser}</>
                            ) : (
                              <><ToggleRight className="mr-1.5 h-3.5 w-3.5" />{t.admin.activateUser}</>
                            )}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-destructive hover:bg-destructive/10"
                            onClick={() => setDeleteTarget(u)}
                            disabled={actionPending}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      )
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div className="hidden overflow-x-auto rounded-lg border bg-card shadow-sm md:block">
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">{t.admin.emailLabel}</th>
                    <th className="px-4 py-3 text-left font-medium">{t.admin.statusLabel}</th>
                    <th className="hidden px-4 py-3 text-left font-medium md:table-cell">{t.admin.createdAt}</th>
                    <th className="hidden px-4 py-3 text-left font-medium lg:table-cell">{t.admin.lastLogin}</th>
                    <th className="hidden px-4 py-3 text-left font-medium md:table-cell">{t.admin.oauthProvider}</th>
                    <th className="px-4 py-3 text-right font-medium">{t.admin.actionLabel}</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((u) => (
                    <tr key={u.id} className="border-b last:border-0 transition-colors hover:bg-muted/30">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-xs font-medium">
                            {(u.email?.charAt(0) ?? "?").toUpperCase()}
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5">
                              <span className="font-medium">{u.email}</span>
                              {u.is_admin && (
                                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                                  {t.admin.adminBadge}
                                </span>
                              )}
                              {!u.is_active && (
                                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
                                  {t.admin.inactiveBadge}
                                </span>
                              )}
                              {isSelf(u.id) && (
                                <span className="text-[10px] text-muted-foreground">{t.admin.you}</span>
                              )}
                            </div>
                            {u.name && <div className="text-xs text-muted-foreground">{u.name}</div>}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">{statusBadge(u.approval_status)}</td>
                      <td className="hidden px-4 py-3 text-muted-foreground whitespace-nowrap md:table-cell">
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="hidden px-4 py-3 text-muted-foreground whitespace-nowrap lg:table-cell">
                        {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : t.admin.neverLoggedIn}
                      </td>
                      <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
                        {u.oauth_provider ?? "—"}
                        {u.totp_enabled && (
                          <span className="ml-1 text-[10px] text-muted-foreground">{t.admin.twoFactor}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {u.approval_status === "pending" ? (
                          <div className="flex justify-end gap-1.5">
                            <Button size="sm" onClick={() => void handleAction(() => api.adminApproveUser(u.id), fillEmail(t.admin.toastApproved, u.email))} disabled={actionPending}>
                              {t.admin.approve}
                            </Button>
                            <Button size="sm" variant="destructive" onClick={() => setRejectTarget(u)} disabled={actionPending}>
                              {t.admin.reject}
                            </Button>
                          </div>
                        ) : (
                          !isSelf(u.id) && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                                  <MoreHorizontal className="h-4 w-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => void handleAction(
                                  () => api.adminToggleAdmin(u.id),
                                  fillEmail(u.is_admin ? t.admin.toastDemoted : t.admin.toastPromoted, u.email),
                                )}>
                                  {u.is_admin ? (
                                    <><ShieldOff className="mr-2 h-4 w-4" />{t.admin.demoteAdmin}</>
                                  ) : (
                                    <><ShieldCheck className="mr-2 h-4 w-4" />{t.admin.promoteAdmin}</>
                                  )}
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => void handleAction(
                                  () => api.adminToggleActive(u.id),
                                  fillEmail(u.is_active ? t.admin.toastDeactivated : t.admin.toastActivated, u.email),
                                )}>
                                  {u.is_active ? (
                                    <><ToggleLeft className="mr-2 h-4 w-4" />{t.admin.deactivateUser}</>
                                  ) : (
                                    <><ToggleRight className="mr-2 h-4 w-4" />{t.admin.activateUser}</>
                                  )}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem className="text-destructive" onClick={() => setDeleteTarget(u)}>
                                  <Trash2 className="mr-2 h-4 w-4" />
                                  {t.admin.deleteUser}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      <Dialog open={!!rejectTarget} onOpenChange={(open) => { if (!open) { setRejectTarget(null); setRejectReason(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.admin.reject} — {rejectTarget?.email}</DialogTitle>
          </DialogHeader>
          <textarea
            className="w-full rounded-md border bg-background p-3 text-sm"
            rows={3}
            placeholder={t.admin.rejectReasonPlaceholder}
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => { setRejectTarget(null); setRejectReason(""); }}>
              {t.admin.cancel}
            </Button>
            <Button variant="destructive" onClick={() => void handleAction(async () => {
              await api.adminRejectUser(rejectTarget!.id, rejectReason || undefined);
              setRejectTarget(null);
              setRejectReason("");
            }, fillEmail(t.admin.toastRejected, rejectTarget?.email ?? ""))} disabled={actionPending}>
              {t.admin.rejectConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.admin.deleteConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.admin.deleteConfirmMessage}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">{deleteTarget?.email}</p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              {t.admin.cancel}
            </Button>
            <Button variant="destructive" onClick={() => void handleAction(async () => {
              await api.adminDeleteUser(deleteTarget!.id);
              setDeleteTarget(null);
            }, fillEmail(t.admin.toastDeleted, deleteTarget?.email ?? ""))} disabled={actionPending}>
              {t.admin.deleteConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
