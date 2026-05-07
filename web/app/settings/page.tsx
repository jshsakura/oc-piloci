"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import AppShell from "@/components/AppShell";
import { TokenManager } from "@/components/TokenManager";
import { LLMProviderManager } from "@/components/LLMProviderManager";
import { useAuthStore } from "@/lib/auth";
import { api, type AuthProviderName } from "@/lib/api";
import type { AuditLog } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import RoutePending from "@/components/RoutePending";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

function ActionBadge({ action }: { action: string }) {
  const isSuccess = action.includes("success") || action.includes("created") || action === "signup";
  const isFail = action.includes("fail") || action.includes("deleted") || action.includes("revoked");
  if (isSuccess) return <Badge variant="default" className="text-xs">{action}</Badge>;
  if (isFail) return <Badge variant="destructive" className="text-xs">{action}</Badge>;
  return <Badge variant="secondary" className="text-xs">{action}</Badge>;
}

function formatKST(iso: string): string {
  try {
    return new Date(iso).toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
  } catch { return iso; }
}

export default function SettingsPage() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwError, setPwError] = useState("");
  const [pwSuccess, setPwSuccess] = useState(false);

  const [totpEnabled, setTotpEnabled] = useState(false);
  const [totpStep, setTotpStep] = useState<"idle" | "setup" | "backup">("idle");
  const [totpQr, setTotpQr] = useState("");
  const [totpSecret, setTotpSecret] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [totpError, setTotpError] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [showDisableForm, setShowDisableForm] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [disableError, setDisableError] = useState("");

  const [disconnecting, setDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState("");
  const [disconnectSuccess, setDisconnectSuccess] = useState(false);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importResult, setImportResult] = useState<{
    projects_imported: number;
    projects_renamed: number;
    memories_imported: number;
    re_embedded: boolean;
  } | null>(null);
  const [reembed, setReembed] = useState(false);

  const { data: recentLogs, isLoading: auditLoading } = useQuery<AuditLog[]>({
    queryKey: ["audit-recent"],
    queryFn: () => api.listAudit(20, 0),
    enabled: !!user,
  });

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) router.replace("/login");
  }, [hasHydrated, isBootstrapping, user, router]);

  if (!hasHydrated || isBootstrapping) {
    return (
      <AppShell>
        <RoutePending title="설정 불러오는 중" description="세션이 복원되면 계정 및 보안 설정을 이어서 표시합니다." />
      </AppShell>
    );
  }

  if (!user) {
    return (
      <RoutePending
        fullScreen
        title="로그인 화면으로 이동 중"
        description="설정 페이지는 로그인 후에만 볼 수 있어 로그인 화면으로 이동합니다."
      />
    );
  }

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError("");
    setPwSuccess(false);
    if (!currentPw || !newPw || !confirmPw) { setPwError("모든 필드를 입력해주세요"); return; }
    if (newPw !== confirmPw) { setPwError("새 비밀번호가 일치하지 않습니다"); return; }
    if (newPw.length < 12) { setPwError("비밀번호는 12자 이상이어야 합니다"); return; }
    try {
      await api.changePassword(currentPw, newPw);
      setPwSuccess(true);
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (err) {
      setPwError(err instanceof Error ? err.message : "비밀번호 변경에 실패했습니다");
    }
  };

  const handle2faEnable = async () => {
    setTotpError("");
    try {
      const data = await api.enable2fa();
      setTotpQr(data.qr);
      setTotpSecret(data.secret);
      setTotpStep("setup");
    } catch (e: unknown) {
      setTotpError((e as Error).message || "2FA 설정 실패");
    }
  };

  const handle2faConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setTotpError("");
    try {
      const data = await api.confirm2fa(totpCode);
      setBackupCodes(data.backup_codes);
      setTotpEnabled(true);
      setTotpStep("backup");
      setTotpCode("");
    } catch (e: unknown) {
      setTotpError((e as Error).message || "코드 확인 실패");
    }
  };

  const handle2faDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    setDisableError("");
    try {
      await api.disable2fa(disablePassword, disableCode);
      setTotpEnabled(false);
      setShowDisableForm(false);
      setDisablePassword("");
      setDisableCode("");
    } catch (e: unknown) {
      setDisableError((e as Error).message || "비활성화 실패");
    }
  };

  const handleExport = async () => {
    setExportError("");
    setExporting(true);
    try {
      const { blob, filename } = await api.exportUserData();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      const message = err instanceof Error ? err.message : "내보내기에 실패했습니다";
      const status = (err as { status?: number })?.status;
      setExportError(status === 429 ? "잠시 후 다시 시도해주세요" : message);
    } finally {
      setExporting(false);
    }
  };

  const handleImport = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fileInput = form.elements.namedItem("archive") as HTMLInputElement | null;
    const file = fileInput?.files?.[0];
    if (!file) {
      setImportError("불러올 .zip 파일을 선택해주세요");
      return;
    }
    setImportError("");
    setImportResult(null);
    setImporting(true);
    try {
      const result = await api.importUserData(file, { reembed });
      setImportResult({
        projects_imported: result.projects_imported,
        projects_renamed: result.projects_renamed,
        memories_imported: result.memories_imported,
        re_embedded: result.re_embedded,
      });
      form.reset();
    } catch (err) {
      const message = err instanceof Error ? err.message : "가져오기에 실패했습니다";
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setImportError("내보낸 서버와 임베딩 모델이 다릅니다. 다시 임베딩을 켜고 시도해주세요.");
      } else if (status === 413) {
        setImportError("파일이 너무 큽니다. 더 작게 나눠 내보내주세요.");
      } else if (status === 429) {
        setImportError("잠시 후 다시 시도해주세요");
      } else {
        setImportError(message);
      }
    } finally {
      setImporting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!user?.oauth_provider) return;
    setDisconnectError("");
    setDisconnectSuccess(false);
    setDisconnecting(true);
    try {
      await api.disconnectProvider(user.oauth_provider as AuthProviderName);
      setDisconnectSuccess(true);
    } catch (err) {
      setDisconnectError(err instanceof Error ? err.message : "연결 끊기에 실패했습니다");
    } finally {
      setDisconnecting(false);
    }
  };

  const providerLabel: Record<string, string> = {
    google: "Google",
    github: "GitHub",
    kakao: "Kakao",
    naver: "Naver",
  };

  return (
    <AppShell>
      <h1 className="text-2xl font-bold">설정</h1>
      <p className="text-sm text-muted-foreground">계정 및 보안 설정을 관리합니다</p>

      <Tabs defaultValue="account" className="mt-6">
        <TabsList className="w-full">
          <TabsTrigger value="account" className="flex-1">계정</TabsTrigger>
          <TabsTrigger value="security" className="flex-1">보안</TabsTrigger>
          <TabsTrigger value="tokens" className="flex-1">토큰</TabsTrigger>
          <TabsTrigger value="llm" className="flex-1">LLM</TabsTrigger>
          <TabsTrigger value="data" className="flex-1">데이터</TabsTrigger>
          <TabsTrigger value="audit" className="flex-1">활동</TabsTrigger>
        </TabsList>

        <TabsContent value="account" className="mt-4 space-y-4">
          <Card>
            <CardHeader><CardTitle>계정 정보</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                <Label>이메일</Label>
                <p className="rounded-md border bg-muted px-3 py-2 font-mono text-sm">{user.email}</p>
              </div>
              <Separator className="my-6" />
              <form onSubmit={handlePasswordChange} className="space-y-3">
                <CardTitle className="text-base">비밀번호 변경</CardTitle>
                <div className="space-y-1.5">
                  <Label>현재 비밀번호</Label>
                  <Input type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>새 비밀번호</Label>
                  <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>새 비밀번호 확인</Label>
                  <Input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
                </div>
                {pwError && <p className="text-sm text-destructive">{pwError}</p>}
                {pwSuccess && <p className="text-sm text-primary">비밀번호가 변경되었습니다</p>}
                <Button type="submit" variant="outline">변경</Button>
              </form>
            </CardContent>
          </Card>

          {user.oauth_provider && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <CardTitle>소셜 로그인</CardTitle>
                  <Badge variant="default">
                    {providerLabel[user.oauth_provider] ?? user.oauth_provider} 연결됨
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {providerLabel[user.oauth_provider] ?? user.oauth_provider} 계정으로 로그인하고 있습니다.
                  연결을 끊으려면 먼저 비밀번호를 설정하세요.
                </p>
                {disconnectError && <p className="text-sm text-destructive">{disconnectError}</p>}
                {disconnectSuccess && (
                  <p className="text-sm text-primary">
                    연결이 끊어졌습니다. 비밀번호로 로그인해주세요.
                  </p>
                )}
                <Button
                  variant="outline"
                  className="text-destructive hover:text-destructive"
                  disabled={disconnecting}
                  onClick={handleDisconnect}
                >
                  {disconnecting ? "처리 중..." : "연결 끊기"}
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="security" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <CardTitle>2FA</CardTitle>
                <Badge variant={totpEnabled ? "default" : "secondary"}>
                  {totpEnabled ? "활성" : "비활성"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {totpStep === "idle" && !totpEnabled && (
                <div>
                  <p className="mb-4 text-sm text-muted-foreground">
                    TOTP 앱(Google Authenticator 등)으로 2FA를 활성화합니다
                  </p>
                  <Button onClick={handle2faEnable}>2FA 활성화</Button>
                  {totpError && <p className="mt-2 text-sm text-destructive">{totpError}</p>}
                </div>
              )}

              {totpStep === "setup" && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">QR 코드를 스캔한 후 인증 코드를 입력하세요</p>
                  {totpQr && (
                    <div>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={totpQr} alt="QR" className="mb-3 size-48 rounded-lg border bg-white p-2" />
                      <p className="text-xs text-muted-foreground">
                        수동 키: <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{totpSecret}</code>
                      </p>
                    </div>
                  )}
                  <form onSubmit={handle2faConfirm} className="flex items-end gap-3 max-w-sm">
                    <div className="flex-1 space-y-1.5">
                      <Label>인증 코드</Label>
                      <Input
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        value={totpCode}
                        onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                        placeholder="123456"
                      />
                    </div>
                    <Button type="submit">확인</Button>
                  </form>
                  {totpError && <p className="text-sm text-destructive">{totpError}</p>}
                </div>
              )}

              {totpStep === "backup" && backupCodes.length > 0 && (
                <div className="space-y-4">
                  <p className="text-sm font-medium text-primary">백업 코드를 안전한 곳에 저장하세요</p>
                  <div className="grid grid-cols-2 gap-2 rounded-md bg-muted p-4 font-mono text-sm">
                    {backupCodes.map((code, i) => <span key={i}>{code}</span>)}
                  </div>
                  <Button variant="outline" onClick={() => setTotpStep("idle")}>확인</Button>
                </div>
              )}

              {totpStep === "idle" && totpEnabled && !showDisableForm && (
                <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => setShowDisableForm(true)}>
                  2FA 비활성화
                </Button>
              )}

              {showDisableForm && (
                <form onSubmit={handle2faDisable} className="max-w-sm space-y-3">
                  <div className="space-y-1.5">
                    <Label>현재 비밀번호</Label>
                    <Input type="password" value={disablePassword} onChange={(e) => setDisablePassword(e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>TOTP 코드</Label>
                    <Input type="text" inputMode="numeric" maxLength={6} value={disableCode} onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ""))} />
                  </div>
                  {disableError && <p className="text-sm text-destructive">{disableError}</p>}
                  <div className="flex gap-2">
                    <Button type="submit" variant="destructive">비활성화</Button>
                    <Button type="button" variant="outline" onClick={() => { setShowDisableForm(false); setDisableError(""); }}>취소</Button>
                  </div>
                </form>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tokens" className="mt-4">
          <Card>
            <CardContent className="pt-6">
              <TokenManager />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="llm" className="mt-4">
          <LLMProviderManager />
        </TabsContent>

        <TabsContent value="data" className="mt-4 space-y-4">
          <Card>
            <CardHeader><CardTitle>내 데이터 내보내기</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                지금까지 piLoci가 정리해 둔 내 프로젝트와 기억을 한 묶음 zip 파일로 받습니다.
                다른 서버로 옮기거나 백업해 둘 때 사용합니다.
              </p>
              <Button onClick={handleExport} disabled={exporting}>
                {exporting ? "내보내는 중..." : "내보내기"}
              </Button>
              {exportError && <p className="text-sm text-destructive">{exportError}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>가져오기</CardTitle></CardHeader>
            <CardContent>
              <form onSubmit={handleImport} className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  다른 piLoci에서 내려받은 zip을 올려두면 현재 계정 안으로 조용히 합쳐집니다.
                  이름이 같은 프로젝트는 자동으로 새 이름으로 들여옵니다.
                </p>
                <div className="space-y-1.5">
                  <Label htmlFor="archive">아카이브 (.zip)</Label>
                  <Input id="archive" name="archive" type="file" accept=".zip,application/zip" />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={reembed}
                    onChange={(e) => setReembed(e.target.checked)}
                    className="size-4"
                  />
                  <span>임베딩 모델이 다르면 다시 계산해서 합치기</span>
                </label>
                {importError && <p className="text-sm text-destructive">{importError}</p>}
                {importResult && (
                  <div className="rounded-md border bg-muted px-3 py-2 text-sm text-muted-foreground">
                    프로젝트 {importResult.projects_imported}개
                    (이름 변경 {importResult.projects_renamed}개) ·
                    기억 {importResult.memories_imported}개
                    {importResult.re_embedded ? " · 다시 임베딩됨" : ""}
                  </div>
                )}
                <Button type="submit" disabled={importing}>
                  {importing ? "가져오는 중..." : "가져오기"}
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="audit" className="mt-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">최근 활동 기록 (최대 20건)</p>
            <Button variant="outline" size="sm" asChild>
              <Link href="/audit">전체 보기</Link>
            </Button>
          </div>
          {auditLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          ) : !recentLogs || recentLogs.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                활동 기록이 없습니다
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {recentLogs.map((log) => (
                <Card key={log.id} className="shadow-none">
                  <CardContent className="flex items-start justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <p className="text-xs text-muted-foreground">{formatKST(log.created_at)}</p>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">{log.ip_address ?? "-"}</p>
                    </div>
                    <ActionBadge action={log.action} />
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}
