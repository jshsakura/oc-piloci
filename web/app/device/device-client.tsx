"use client";

import { useEffect, useState } from "react";
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

  // Pre-fill from ?code=ABCD-1234 (the verification_uri_complete the CLI prints).
  useEffect(() => {
    const initial = params.get("code");
    if (initial) setCode(normalizeCode(initial));
  }, [params]);

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
    setStatus(action === "approve" ? "approving" : "idle");
    setErrorMessage(null);
    try {
      const res = await fetch("/api/device/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ user_code: code, action }),
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
        title={t.device.pendingTitle}
        description={t.device.readyDesc}
      />
    );
  }

  return (
    <AppShell>
      <div className="mx-auto flex w-full max-w-md flex-col gap-4 px-4 py-8">
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

            {errorMessage && status === "error" && (
              <div
                className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 shadow-sm dark:border-red-800 dark:bg-red-950 dark:text-red-200"
                role="alert"
              >
                <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
            )}

            {status === "approved" && (
              <div className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 shadow-sm dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                <span>{t.device.successMessage}</span>
              </div>
            )}

            {status === "denied" && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow-sm dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
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
                  !CODE_REGEX.test(code)
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
