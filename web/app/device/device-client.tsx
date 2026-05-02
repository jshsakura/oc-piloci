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
      setErrorMessage("코드 형식은 ABCD-1234 입니다.");
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
        setErrorMessage(data.error ?? `서버가 ${res.status} 응답을 반환했습니다.`);
        return;
      }
      setStatus(action === "approve" ? "approved" : "denied");
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof Error ? err.message : "네트워크 오류");
    }
  };

  if (!hasHydrated || isBootstrapping || !user) {
    return (
      <RoutePending
        title="기기 승인 페이지 준비 중"
        description="로그인 상태를 확인한 뒤 기기 승인 화면을 보여 드립니다."
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
              기기 승인
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-sm text-muted-foreground leading-relaxed">
              터미널의 <code className="rounded bg-muted px-1 py-0.5 text-[11px]">piloci login</code>{" "}
              출력에 표시된 8자리 코드를 입력하고 승인하면 해당 기기에 토큰이 자동 발급됩니다.
            </p>

            <div className="space-y-2">
              <label className="text-xs font-medium text-foreground" htmlFor="user-code">
                인증 코드
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
                <span>승인 완료. 이제 터미널로 돌아가시면 자동으로 진행됩니다.</span>
              </div>
            )}

            {status === "denied" && (
              <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow-sm dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                요청을 거부했습니다. 새 코드로 다시 시도해 주세요.
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
                {status === "approving" ? "승인 중…" : "이 기기 승인"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => submit("deny")}
                disabled={status === "approving" || status === "approved" || !CODE_REGEX.test(code)}
              >
                거부
              </Button>
            </div>
          </CardContent>
        </Card>

        <p className="px-1 text-xs text-muted-foreground">
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">piloci login</code>{" "}
          또는{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[11px]">piloci setup</code>{" "}
          명령으로 발급된 코드입니다.
        </p>
      </div>
    </AppShell>
  );
}
