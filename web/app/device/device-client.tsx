"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, ShieldAlert, Smartphone } from "lucide-react";

import AppShell from "@/components/AppShell";
import RoutePending from "@/components/RoutePending";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";

// Display rules — keep human-typeable codes consistent with the backend
// (DEVICE_PREFIX uses ABCD-1234 style with the unambiguous alphabet).
const CODE_REGEX = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/i;

function normalizeCode(raw: string): string {
  // Strip whitespace, uppercase, and gracefully accept the dashless form.
  const clean = raw.replace(/[^A-Za-z0-9-]/g, "").toUpperCase();
  if (clean.length === 8 && !clean.includes("-")) {
    return `${clean.slice(0, 4)}-${clean.slice(4)}`;
  }
  return clean;
}

type Status = "idle" | "approving" | "approved" | "denied" | "error";

export default function DeviceClient() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
  const { t } = useTranslation();

  const [code, setCode] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const allKinds = useMemo(
    () => t.device.targets.list.map((p) => p.kind),
    [t.device.targets.list]
  );
  // Start empty — pre-fill with detected clients once the code is resolved.
  const [selected, setSelected] = useState<Set<string>>(() => new Set<string>());
  const [detectedFetched, setDetectedFetched] = useState(false);
  const [detectedKinds, setDetectedKinds] = useState<string[]>([]);

  useEffect(() => {
    // When the locale flips the kind list might change shape; keep selection
    // aligned to the current set of known kinds.
    setSelected((prev) => new Set(allKinds.filter((k) => prev.has(k))));
  }, [allKinds]);

  const toggleKind = (kind: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };

  // Pre-fill from ?code=ABCD-1234 (the verification_uri_complete the CLI prints).
  useEffect(() => {
    const initial = params.get("code");
    if (initial) setCode(normalizeCode(initial));
  }, [params]);

  // Fetch detected clients when code becomes valid; auto-select them once.
  useEffect(() => {
    if (!CODE_REGEX.test(code) || detectedFetched) return;
    let cancelled = false;
    fetch(`/auth/device/info?code=${encodeURIComponent(code)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { detected?: string[] } | null) => {
        if (cancelled || !data) return;
        const kinds = (data.detected ?? []).filter((k) =>
          allKinds.includes(k)
        );
        setDetectedKinds(kinds);
        if (kinds.length > 0) setSelected(new Set(kinds));
        setDetectedFetched(true);
      })
      .catch(() => {
        if (!cancelled) setDetectedFetched(true);
      });
    return () => { cancelled = true; };
  }, [code, detectedFetched, allKinds]);

  // Auth gate — push the user to /login but keep ?code=... so they come back here.
  useEffect(() => {
    if (!hasHydrated || isBootstrapping) return;
    if (!user) {
      const next = encodeURIComponent(
        `/device${code ? `?code=${encodeURIComponent(code)}` : ""}`
      );
      router.replace(`/login?next=${next}`);
    }
  }, [hasHydrated, isBootstrapping, user, router, code]);

  const submit = async (action: "approve" | "deny") => {
    if (!CODE_REGEX.test(code)) {
      setStatus("error");
      setErrorMessage(t.device.error.invalidFormat);
      return;
    }
    if (action === "approve" && selected.size === 0) {
      setStatus("error");
      setErrorMessage(t.device.targets.emptyError);
      return;
    }
    setStatus(action === "approve" ? "approving" : "idle");
    setErrorMessage(null);
    try {
      const body: Record<string, unknown> = { user_code: code, action };
      if (action === "approve") {
        body.targets = allKinds.filter((k) => selected.has(k));
      }
      const res = await fetch("/api/device/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        setStatus("error");
        setErrorMessage(data.error ?? `${t.device.error.serverPrefix} ${res.status} ${t.device.error.serverSuffix}`);
        return;
      }
      setStatus(action === "approve" ? "approved" : "denied");
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof Error ? err.message : t.device.error.network);
    }
  };

  if (!hasHydrated || isBootstrapping || !user) {
    return (
      <RoutePending
        fullScreen
        title={t.device.pendingTitle}
        description={t.device.readyDesc}
      />
    );
  }

  return (
    <AppShell>
      <div className="mx-auto flex w-full max-w-md flex-col gap-4 py-8">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Smartphone className="size-5 text-muted-foreground" />
              {t.device.cardTitle}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-sm text-muted-foreground leading-relaxed">
              {t.device.intro1}<code className="rounded bg-muted px-1 py-0.5 text-[11px]">piloci login</code>{t.device.intro2}
            </p>

            <div className="space-y-2">
              <label className="text-xs font-medium text-foreground" htmlFor="user-code">
                {t.device.codeLabel}
              </label>
              <Input
                id="user-code"
                value={code}
                onChange={(e) => setCode(normalizeCode(e.target.value))}
                placeholder="ABCD-1234"
                autoFocus
                maxLength={9}
                className="font-mono text-base tracking-widest uppercase"
                disabled={status === "approving" || status === "approved"}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-foreground">
                  {t.device.targets.title}
                </span>
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <button
                    type="button"
                    className="hover:text-foreground"
                    onClick={() => setSelected(new Set(allKinds))}
                    disabled={status === "approving" || status === "approved"}
                  >
                    {t.device.targets.selectAll}
                  </button>
                  <span className="text-border">·</span>
                  <button
                    type="button"
                    className="hover:text-foreground"
                    onClick={() => setSelected(new Set())}
                    disabled={status === "approving" || status === "approved"}
                  >
                    {t.device.targets.clearAll}
                  </button>
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                {t.device.targets.hint}
              </p>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {t.device.targets.list.map((p) => {
                  const checked = selected.has(p.kind);
                  const disabled = status === "approving" || status === "approved";
                  return (
                    <label
                      key={p.kind}
                      className={`flex min-w-0 items-start gap-2 rounded-md border px-2.5 py-2 text-xs transition-colors ${
                        checked
                          ? "border-primary/40 bg-primary/5"
                          : "border-border bg-background hover:bg-muted/40"
                      } ${disabled ? "opacity-60" : "cursor-pointer"}`}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 size-3.5 accent-primary"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggleKind(p.kind)}
                      />
                      <span className="flex flex-col leading-tight min-w-0">
                        <span className="flex items-center gap-1.5 font-medium text-foreground">
                          {p.label}
                          {detectedKinds.includes(p.kind) && (
                            <span className="rounded bg-primary/10 px-1 py-0.5 text-[9px] font-normal text-primary">
                              {t.device.targets.detectedBadge}
                            </span>
                          )}
                        </span>
                        <span className="font-mono text-[10px] text-muted-foreground break-all">
                          {p.path}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>

            {errorMessage && status === "error" && (
              <div
                className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
                role="alert"
              >
                <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
            )}

            {status === "approved" && (
              <div className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                <span>{t.device.successMessage}</span>
              </div>
            )}

            {status === "denied" && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                {t.device.deniedMessage}
              </div>
            )}

            <div className="flex gap-2 pt-2">
              <Button
                type="button"
                className="flex-1"
                onClick={() => submit("approve")}
                disabled={
                  status === "approving" ||
                  status === "approved" ||
                  !CODE_REGEX.test(code) ||
                  selected.size === 0
                }
              >
                {status === "approving" ? t.device.approving : t.device.approveButton}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => submit("deny")}
                disabled={status === "approving" || status === "approved" || !CODE_REGEX.test(code)}
              >
                {t.device.denyButton}
              </Button>
            </div>
          </CardContent>
        </Card>

        <p className="px-1 text-xs text-muted-foreground">
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">piloci login</code>
          {t.device.footer1}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">piloci setup</code>
          {t.device.footer2}
        </p>
      </div>
    </AppShell>
  );
}
