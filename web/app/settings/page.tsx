"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { TokenManager } from "@/components/TokenManager";
import { useAuthStore } from "@/lib/auth";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import RoutePending from "@/components/RoutePending";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

const MCP_EXAMPLE = `{
  "mcpServers": {
    "piloci": {
      "type": "http",
      "url": "https://piloci.jshsakura.com/sse",
      "headers": { "Authorization": "Bearer YOUR_TOKEN_HERE" }
    }
  }
}`;

export default function SettingsPage() {
  const router = useRouter();
  const { user, hasHydrated } = useAuthStore();

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

  const [copiedMcp, setCopiedMcp] = useState(false);

  useEffect(() => {
    if (hasHydrated && !user) router.replace("/login");
  }, [hasHydrated, user, router]);

  if (!hasHydrated) {
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

  const handleCopyMcp = async () => {
    await navigator.clipboard.writeText(MCP_EXAMPLE);
    setCopiedMcp(true);
    setTimeout(() => setCopiedMcp(false), 2000);
  };

  return (
    <AppShell>
      <h1 className="text-2xl font-bold">설정</h1>
      <p className="text-sm text-muted-foreground">계정 및 보안 설정을 관리합니다</p>

      <Tabs defaultValue="account" className="mt-6">
        <TabsList>
          <TabsTrigger value="account">계정</TabsTrigger>
          <TabsTrigger value="security">보안</TabsTrigger>
          <TabsTrigger value="tokens">토큰</TabsTrigger>
          <TabsTrigger value="audit">감사</TabsTrigger>
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

        <TabsContent value="audit" className="mt-4">
          <Card>
            <CardContent className="flex items-center justify-between py-6">
              <p className="text-sm text-muted-foreground">세션 활동 및 접근 로그를 확인합니다</p>
              <Button variant="outline" asChild>
                <Link href="/audit">감사 로그 보기</Link>
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <div className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">MCP 설정</h2>
        <div className="relative rounded-md bg-muted p-4">
          <pre className="overflow-x-auto font-mono text-sm">{MCP_EXAMPLE}</pre>
          <Button size="sm" variant="outline" className="absolute right-3 top-3" onClick={handleCopyMcp}>
            {copiedMcp ? "복사됨" : "복사"}
          </Button>
        </div>
      </div>
    </AppShell>
  );
}
