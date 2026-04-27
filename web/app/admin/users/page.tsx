"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  DialogFooter,
} from "@/components/ui/dialog";
import RoutePending from "@/components/RoutePending";

type StatusFilter = "all" | "pending" | "approved" | "rejected";

export default function AdminUsersPage() {
  const router = useRouter();
  const { user, hasHydrated } = useAuthStore();
  const { t } = useTranslation();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [rejectTarget, setRejectTarget] = useState<AdminUser | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [actionPending, setActionPending] = useState(false);

  useEffect(() => {
    if (hasHydrated && (!user || !user.is_admin)) {
      router.replace("/dashboard");
    }
  }, [hasHydrated, user, router]);

  const fetchUsers = async (status?: string) => {
    setLoading(true);
    try {
      const result = await api.adminListUsers(status);
      setUsers(result as AdminUser[]);
    } catch {
      setUsers([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.is_admin) {
      void fetchUsers(filter === "all" ? undefined : filter);
    }
  }, [filter, user?.is_admin]);

  if (!hasHydrated || !user) return <AppShell><RoutePending title={t.admin.title} description={t.admin.description} /></AppShell>;
  if (!user.is_admin) return <AppShell><RoutePending title={t.admin.title} description={t.admin.description} fullScreen /></AppShell>;

  const handleApprove = async (userId: string) => {
    setActionPending(true);
    try {
      await api.adminApproveUser(userId);
      void fetchUsers(filter === "all" ? undefined : filter);
    } finally {
      setActionPending(false);
    }
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    setActionPending(true);
    try {
      await api.adminRejectUser(rejectTarget.id, rejectReason || undefined);
      setRejectTarget(null);
      setRejectReason("");
      void fetchUsers(filter === "all" ? undefined : filter);
    } finally {
      setActionPending(false);
    }
  };

  const filters: { key: StatusFilter; label: string }[] = [
    { key: "all", label: t.admin.filterAll },
    { key: "pending", label: t.admin.filterPending },
    { key: "approved", label: t.admin.filterApproved },
    { key: "rejected", label: t.admin.filterRejected },
  ];

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
      approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
      rejected: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    };
    return (
      <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${colors[status] ?? ""}`}>
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

        <div className="flex gap-2">
          {filters.map((f) => (
            <Button
              key={f.key}
              variant={filter === f.key ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </Button>
          ))}
        </div>

        {loading ? (
          <p className="text-sm text-muted-foreground">...</p>
        ) : users.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t.admin.emptyMessage}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">{t.admin.createdAt}</th>
                  <th className="px-4 py-3 text-left font-medium">Email</th>
                  <th className="px-4 py-3 text-left font-medium">Status</th>
                  <th className="px-4 py-3 text-left font-medium">{t.admin.oauthProvider}</th>
                  <th className="px-4 py-3 text-left font-medium">{t.admin.reviewedAt}</th>
                  <th className="px-4 py-3 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b last:border-0">
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div>{u.email}</div>
                      {u.name && <div className="text-xs text-muted-foreground">{u.name}</div>}
                    </td>
                    <td className="px-4 py-3">{statusBadge(u.approval_status)}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {u.oauth_provider ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                      {u.reviewed_at ? new Date(u.reviewed_at).toLocaleDateString() : t.admin.noReviewer}
                      {u.rejection_reason && (
                        <div className="mt-0.5 text-xs text-red-600 dark:text-red-400">{u.rejection_reason}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {u.approval_status === "pending" && (
                        <div className="flex justify-end gap-2">
                          <Button size="sm" onClick={() => void handleApprove(u.id)} disabled={actionPending}>
                            {t.admin.approve}
                          </Button>
                          <Button size="sm" variant="destructive" onClick={() => setRejectTarget(u)} disabled={actionPending}>
                            {t.admin.reject}
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
            <Button variant="destructive" onClick={() => void handleReject()} disabled={actionPending}>
              {t.admin.rejectConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
