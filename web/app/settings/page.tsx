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
import { useTranslation } from "@/lib/i18n";
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
  const { t } = useTranslation();

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
        <RoutePending title={t.settings.pending.loadingTitle} description={t.settings.pending.loadingDesc} />
      </AppShell>
    );
  }

  if (!user) {
    return (
      <RoutePending
        fullScreen
        title={t.settings.pending.redirectTitle}
        description={t.settings.pending.redirectDesc}
      />
    );
  }

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError("");
    setPwSuccess(false);
    if (!currentPw || !newPw || !confirmPw) { setPwError(t.settings.account.validation.allFieldsRequired); return; }
    if (newPw !== confirmPw) { setPwError(t.settings.account.validation.passwordMismatch); return; }
    if (newPw.length < 12) { setPwError(t.settings.account.validation.passwordMin); return; }
    try {
      await api.changePassword(currentPw, newPw);
      setPwSuccess(true);
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (err) {
      setPwError(err instanceof Error ? err.message : t.settings.account.validation.changeFailed);
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
      setTotpError((e as Error).message || t.settings.security.error.setupFailed);
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
      setTotpError((e as Error).message || t.settings.security.error.confirmFailed);
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
      setDisableError((e as Error).message || t.settings.security.error.disableFailed);
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
      const message = err instanceof Error ? err.message : t.settings.dataExport.error.generic;
      const status = (err as { status?: number })?.status;
      setExportError(status === 429 ? t.settings.dataExport.error.throttled : message);
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
      setImportError(t.settings.dataImport.error.missingFile);
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
      const message = err instanceof Error ? err.message : t.settings.dataImport.error.generic;
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setImportError(t.settings.dataImport.error.embeddingMismatch);
      } else if (status === 413) {
        setImportError(t.settings.dataImport.error.tooLarge);
      } else if (status === 429) {
        setImportError(t.settings.dataImport.error.throttled);
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
      setDisconnectError(err instanceof Error ? err.message : t.settings.account.validation.disconnectFailed);
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
      <div className="pi-page">
        <section className="pi-page-hero">
          <p className="pi-eyebrow">{t.settings.eyebrow}</p>
          <h1 className="pi-title mt-2">{t.settings.title}</h1>
          <p className="pi-subtitle">{t.settings.description}</p>
        </section>

      <Tabs defaultValue="account">
        <TabsList className="pi-panel h-auto w-full flex-wrap justify-start gap-1 p-1">
          <TabsTrigger value="account" className="flex-1">{t.settings.tabs.account}</TabsTrigger>
          <TabsTrigger value="security" className="flex-1">{t.settings.tabs.security}</TabsTrigger>
          <TabsTrigger value="tokens" className="flex-1">{t.settings.tabs.tokens}</TabsTrigger>
          <TabsTrigger value="llm" className="flex-1">{t.settings.tabs.llm}</TabsTrigger>
          <TabsTrigger value="data" className="flex-1">{t.settings.tabs.data}</TabsTrigger>
          <TabsTrigger value="audit" className="flex-1">{t.settings.tabs.audit}</TabsTrigger>
        </TabsList>

        <TabsContent value="account" className="mt-4 space-y-4">
          <Card>
            <CardHeader><CardTitle>{t.settings.account.infoTitle}</CardTitle></CardHeader>
            <CardContent>
              <div className="space-y-2">
                <Label>{t.settings.account.emailLabel}</Label>
                <p className="rounded-md border bg-muted px-3 py-2 font-mono text-sm">{user.email}</p>
              </div>
              <Separator className="my-6" />
              <form onSubmit={handlePasswordChange} className="space-y-3">
                <CardTitle className="text-base">{t.settings.account.passwordChangeTitle}</CardTitle>
                <div className="space-y-1.5">
                  <Label>{t.settings.account.currentPassword}</Label>
                  <Input type="password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>{t.settings.account.newPassword}</Label>
                  <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label>{t.settings.account.confirmPassword}</Label>
                  <Input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
                </div>
                {pwError && <p className="text-sm text-destructive">{pwError}</p>}
                {pwSuccess && <p className="text-sm text-primary">{t.settings.account.passwordChanged}</p>}
                <Button type="submit" variant="outline">{t.settings.account.submit}</Button>
              </form>
            </CardContent>
          </Card>

          {user.oauth_provider && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <CardTitle>{t.settings.account.socialLoginTitle}</CardTitle>
                  <Badge variant="default">
                    {providerLabel[user.oauth_provider] ?? user.oauth_provider} {t.settings.account.connected}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {providerLabel[user.oauth_provider] ?? user.oauth_provider}{t.settings.account.socialDesc}
                </p>
                {disconnectError && <p className="text-sm text-destructive">{disconnectError}</p>}
                {disconnectSuccess && (
                  <p className="text-sm text-primary">
                    {t.settings.account.disconnected}
                  </p>
                )}
                <Button
                  variant="outline"
                  className="text-destructive hover:text-destructive"
                  disabled={disconnecting}
                  onClick={handleDisconnect}
                >
                  {disconnecting ? t.settings.account.disconnecting : t.settings.account.disconnect}
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="security" className="mt-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <CardTitle>{t.settings.security.title}</CardTitle>
                <Badge variant={totpEnabled ? "default" : "secondary"}>
                  {totpEnabled ? t.settings.security.enabled : t.settings.security.disabled}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {totpStep === "idle" && !totpEnabled && (
                <div>
                  <p className="mb-4 text-sm text-muted-foreground">
                    {t.settings.security.setupDesc}
                  </p>
                  <Button onClick={handle2faEnable}>{t.settings.security.enableButton}</Button>
                  {totpError && <p className="mt-2 text-sm text-destructive">{totpError}</p>}
                </div>
              )}

              {totpStep === "setup" && (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">{t.settings.security.setupGuide}</p>
                  {totpQr && (
                    <div>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={totpQr} alt="QR" className="mb-3 size-48 rounded-lg border bg-white p-2" />
                      <p className="text-xs text-muted-foreground">
                        {t.settings.security.secretKey}: <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{totpSecret}</code>
                      </p>
                    </div>
                  )}
                  <form onSubmit={handle2faConfirm} className="flex items-end gap-3 max-w-sm">
                    <div className="flex-1 space-y-1.5">
                      <Label>{t.settings.security.codeLabel}</Label>
                      <Input
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        value={totpCode}
                        onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                        placeholder="123456"
                      />
                    </div>
                    <Button type="submit">{t.settings.security.confirmButton}</Button>
                  </form>
                  {totpError && <p className="text-sm text-destructive">{totpError}</p>}
                </div>
              )}

              {totpStep === "backup" && backupCodes.length > 0 && (
                <div className="space-y-4">
                  <p className="text-sm font-medium text-primary">{t.settings.security.backupTitle}</p>
                  <div className="grid grid-cols-2 gap-2 rounded-md bg-muted p-4 font-mono text-sm">
                    {backupCodes.map((code, i) => <span key={i}>{code}</span>)}
                  </div>
                  <Button variant="outline" onClick={() => setTotpStep("idle")}>{t.settings.security.confirmButton}</Button>
                </div>
              )}

              {totpStep === "idle" && totpEnabled && !showDisableForm && (
                <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => setShowDisableForm(true)}>
                  {t.settings.security.disableButton}
                </Button>
              )}

              {showDisableForm && (
                <form onSubmit={handle2faDisable} className="max-w-sm space-y-3">
                  <div className="space-y-1.5">
                    <Label>{t.settings.security.disablePasswordLabel}</Label>
                    <Input type="password" value={disablePassword} onChange={(e) => setDisablePassword(e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>{t.settings.security.disableCodeLabel}</Label>
                    <Input type="text" inputMode="numeric" maxLength={6} value={disableCode} onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ""))} />
                  </div>
                  {disableError && <p className="text-sm text-destructive">{disableError}</p>}
                  <div className="flex gap-2">
                    <Button type="submit" variant="destructive">{t.settings.security.disableSubmit}</Button>
                    <Button type="button" variant="outline" onClick={() => { setShowDisableForm(false); setDisableError(""); }}>{t.settings.security.cancelButton}</Button>
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
            <CardHeader><CardTitle>{t.settings.dataExport.title}</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {t.settings.dataExport.desc}
              </p>
              <Button onClick={handleExport} disabled={exporting}>
                {exporting ? t.settings.dataExport.exporting : t.settings.dataExport.export}
              </Button>
              {exportError && <p className="text-sm text-destructive">{exportError}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>{t.settings.dataImport.title}</CardTitle></CardHeader>
            <CardContent>
              <form onSubmit={handleImport} className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  {t.settings.dataImport.desc}
                </p>
                <div className="space-y-1.5">
                  <Label htmlFor="archive">{t.settings.dataImport.archiveLabel}</Label>
                  <Input id="archive" name="archive" type="file" accept=".zip,application/zip" />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={reembed}
                    onChange={(e) => setReembed(e.target.checked)}
                    className="size-4"
                  />
                  <span>{t.settings.dataImport.reembedToggle}</span>
                </label>
                {importError && <p className="text-sm text-destructive">{importError}</p>}
                {importResult && (
                  <div className="rounded-md border bg-muted px-3 py-2 text-sm text-muted-foreground">
                    {t.settings.dataImport.result.projects} {importResult.projects_imported}{t.settings.dataImport.result.unit}
                    {" "}({t.settings.dataImport.result.renamed} {importResult.projects_renamed}{t.settings.dataImport.result.unit}) ·
                    {" "}{t.settings.dataImport.result.memories} {importResult.memories_imported}{t.settings.dataImport.result.unit}
                    {importResult.re_embedded ? t.settings.dataImport.result.reembedded : ""}
                  </div>
                )}
                <Button type="submit" disabled={importing}>
                  {importing ? t.settings.dataImport.importing : t.settings.dataImport.import}
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="audit" className="mt-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">{t.settings.audit.recentTitle}</p>
            <Button variant="outline" size="sm" asChild>
              <Link href="/audit">{t.settings.audit.viewAll}</Link>
            </Button>
          </div>
          {auditLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          ) : !recentLogs || recentLogs.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                {t.settings.audit.empty}
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
      </div>
    </AppShell>
  );
}
