"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Copy, Trash2, Check, ChevronUp } from "lucide-react";
import { api } from "@/lib/api";
import type { ApiToken, CreatedToken, Project } from "@/lib/types";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function CopyBlock({ value, label, sensitive }: { value: string; label?: string; sensitive?: boolean }) {
  const [copied, setCopied] = useState(false);
  const { t } = useTranslation();

  const handleCopy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const display = sensitive
    ? `${value.slice(0, 12)}${"·".repeat(24)}`
    : value;

  return (
    <div className="space-y-1.5">
      {label && <p className="text-xs text-muted-foreground">{label}</p>}
      <div className="flex items-center gap-2 rounded-md border bg-muted p-3">
        {sensitive ? (
          <code className="flex-1 truncate font-mono text-xs">{display}</code>
        ) : (
          <pre className="flex-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-xs leading-relaxed select-text">{value}</pre>
        )}
        <Button
          size="sm"
          variant={copied ? "default" : "outline"}
          className="shrink-0 gap-1.5 text-xs"
          onClick={handleCopy}
        >
          {copied ? <><Check className="size-3" />{t.common.copied}</> : <><Copy className="size-3" />{t.common.copy}</>}
        </Button>
      </div>
    </div>
  );
}

function buildMcpConfigs(token: string, baseUrl: string) {
  const auth = `Bearer ${token}`;
  const httpUrl = `${baseUrl}/mcp/http`;
  return {
    claude: JSON.stringify({
      mcpServers: { piloci: { type: "http", url: httpUrl, headers: { Authorization: auth } } },
    }, null, 2),
    opencode: JSON.stringify({
      $schema: "https://opencode.ai/config.json",
      mcp: { piloci: { type: "remote", url: httpUrl, enabled: true, headers: { Authorization: auth } } },
    }, null, 2),
  };
}

function SetupDialog({ data, onClose }: { data: CreatedToken; onClose: () => void }) {
  const { t } = useTranslation();
  const baseUrl = typeof window !== "undefined" ? window.location.origin : "https://piloci.opencourse.kr";
  const configs = buildMcpConfigs(data.token, baseUrl);
  const hookJson = data.setup ? JSON.stringify(data.setup.hook_config, null, 2) : null;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.tokenManager.tokenCreated}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="token">
          <TabsList className="w-full">
            <TabsTrigger value="token" className="flex-1">{t.tokenManager.tabs.token}</TabsTrigger>
            <TabsTrigger value="mcp" className="flex-1">{t.tokenManager.tabs.mcpServer}</TabsTrigger>
            {hookJson && <TabsTrigger value="hook" className="flex-1">{t.tokenManager.tabs.stopHook}</TabsTrigger>}
          </TabsList>

          <TabsContent value="token" className="space-y-3 pt-1">
            <p className="text-sm text-destructive">{t.tokenManager.tokenWarning}</p>
            <CopyBlock value={data.token} sensitive />
          </TabsContent>

          <TabsContent value="mcp" className="pt-1">
            <Tabs defaultValue="claude">
              <TabsList>
                <TabsTrigger value="claude">Claude</TabsTrigger>
                <TabsTrigger value="opencode">OpenCode</TabsTrigger>
              </TabsList>
              <TabsContent value="claude" className="space-y-2 pt-3">
                <p className="text-xs text-muted-foreground">
                  Claude Desktop / Claude Code / Cursor — <code className="rounded bg-muted px-1 py-0.5">.mcp.json</code> 또는 <code className="rounded bg-muted px-1 py-0.5">claude_desktop_config.json</code>
                </p>
                <CopyBlock value={configs.claude} />
              </TabsContent>
              <TabsContent value="opencode" className="space-y-2 pt-3">
                <p className="text-xs text-muted-foreground">
                  OpenCode — <code className="rounded bg-muted px-1 py-0.5">opencode.json</code> (<code className="rounded bg-muted px-1 py-0.5">type: &quot;remote&quot;</code> 사용)
                </p>
                <CopyBlock value={configs.opencode} />
              </TabsContent>
            </Tabs>
          </TabsContent>

          {hookJson && (
            <TabsContent value="hook" className="space-y-3 pt-1">
              <p className="text-sm text-muted-foreground">
                <code className="rounded bg-muted px-1 py-0.5 text-xs">~/.claude/settings.json</code>
                {t.tokenManager.hookInstructions}
              </p>
              <CopyBlock value={hookJson} />
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                <strong>{t.tokenManager.hookCondition}</strong>
              </div>
            </TabsContent>
          )}
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

export function TokenManager() {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [showCreate, setShowCreate] = useState(false);
  const [formName, setFormName] = useState("");
  const [formScope, setFormScope] = useState<"user" | "project">("user");
  const [formProjectId, setFormProjectId] = useState("");
  const [formExpireDays, setFormExpireDays] = useState<number | null>(365);
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);
  const [selectedTokenId, setSelectedTokenId] = useState<string | null>(null);

  const { data: tokens = [], isLoading } = useQuery<ApiToken[]>({
    queryKey: ["tokens"],
    queryFn: () => api.listTokens(),
  });

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });

  const createMutation = useMutation({
    mutationFn: ({
      name,
      scope,
      project_id,
      expire_days,
    }: {
      name: string;
      scope: "user" | "project";
      project_id?: string;
      expire_days?: number | null;
    }) => api.createToken(name, scope, project_id, expire_days) as Promise<CreatedToken>,
    onSuccess: (data) => {
      setCreatedToken(data);
      queryClient.invalidateQueries({ queryKey: ["tokens"] });
      setShowCreate(false);
      setFormName("");
      setFormScope("user");
      setFormProjectId("");
      setFormExpireDays(365);
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.revokeToken(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tokens"] }),
  });

  const handleCreate = (e: { preventDefault(): void }) => {
    e.preventDefault();
    if (!formName.trim()) return;
    createMutation.mutate({
      name: formName.trim(),
      scope: formScope,
      project_id: formScope === "project" && formProjectId ? formProjectId : undefined,
      expire_days: formExpireDays,
    });
  };

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{t.tokenManager.desc}</p>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1 size-4" /> {t.tokenManager.issue}
        </Button>
      </div>

      {createdToken && (
        <SetupDialog data={createdToken} onClose={() => setCreatedToken(null)} />
      )}

      {showCreate && (
        <Card className="border-dashed bg-muted/30 shadow-none">
          <CardContent className="p-4">
            <form onSubmit={handleCreate} className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t.tokenManager.formName}</Label>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder={t.tokenManager.formNamePlaceholder}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t.tokenManager.formScope}</Label>
                <Select
                  value={formScope}
                  onValueChange={(v: "user" | "project") => {
                    setFormScope(v);
                    if (v === "user") setFormProjectId("");
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="user">{t.tokenManager.scopeUser}</SelectItem>
                    <SelectItem value="project">{t.tokenManager.scopeProject}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {formScope === "project" && (
                <div className="space-y-1.5">
                  <Label>{t.tokenManager.formProject}</Label>
                  <Select value={formProjectId} onValueChange={setFormProjectId}>
                    <SelectTrigger>
                      <SelectValue placeholder={t.tokenManager.selectProject} />
                    </SelectTrigger>
                    <SelectContent>
                      {projects.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.name} ({p.slug})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div className="space-y-1.5">
                <Label>{t.tokenManager.formExpire}</Label>
                <Select
                  value={formExpireDays === null ? "none" : String(formExpireDays)}
                  onValueChange={(v) => setFormExpireDays(v === "none" ? null : Number(v))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="30">{t.tokenManager.expireOptions.d30}</SelectItem>
                    <SelectItem value="90">{t.tokenManager.expireOptions.d90}</SelectItem>
                    <SelectItem value="180">{t.tokenManager.expireOptions.d180}</SelectItem>
                    <SelectItem value="365">{t.tokenManager.expireOptions.d365}</SelectItem>
                    <SelectItem value="none">{t.tokenManager.expireOptions.none}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {createMutation.error && (
                <p className="text-sm text-destructive">
                  {(createMutation.error as Error).message}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
                  {t.tokenManager.cancel}
                </Button>
                <Button
                  type="submit"
                  disabled={createMutation.isPending || !formName.trim()}
                >
                  {createMutation.isPending ? t.tokenManager.issuing : t.tokenManager.issue}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : tokens.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            {t.tokenManager.noTokens}
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.tokenManager.tableHeaders.name}</TableHead>
                <TableHead className="hidden sm:table-cell">{t.tokenManager.tableHeaders.scope}</TableHead>
                <TableHead className="hidden md:table-cell">{t.tokenManager.tableHeaders.issued}</TableHead>
                <TableHead className="hidden md:table-cell">{t.tokenManager.tableHeaders.lastUsed}</TableHead>
                <TableHead>{t.tokenManager.tableHeaders.expires}</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((token) => {
                const project = token.project_id
                  ? projects.find((p) => p.id === token.project_id)
                  : undefined;
                const isExpired = token.expires_at ? new Date(token.expires_at) < new Date() : false;
                return (
                  <TableRow
                    key={token.token_id}
                    className={`cursor-pointer ${selectedTokenId === token.token_id ? "bg-accent/50" : ""}`}
                    onClick={() => setSelectedTokenId(selectedTokenId === token.token_id ? null : token.token_id)}
                  >
                    <TableCell className="font-medium">
                      <div className="flex flex-col gap-0.5">
                        <span>
                          {token.name}
                          {project && (
                            <span className="ml-2 text-xs text-muted-foreground">
                              ({project.slug})
                            </span>
                          )}
                        </span>
                        <span className="sm:hidden">
                          <Badge variant={token.scope === "user" ? "default" : "secondary"} className="text-xs">
                            {token.scope}
                          </Badge>
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <Badge variant={token.scope === "user" ? "default" : "secondary"}>
                        {token.scope}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                      {formatDate(token.created_at)}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-sm text-muted-foreground">
                      {token.last_used_at ? formatDate(token.last_used_at) : "-"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {token.expires_at
                        ? isExpired
                          ? <span className="text-destructive">{t.tokenManager.expired}</span>
                          : formatDate(token.expires_at)
                        : t.tokenManager.expiresNone}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(`"${token.name}" ${t.tokenManager.confirmRevoke}`)) {
                            revokeMutation.mutate(token.token_id);
                          }
                        }}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {selectedTokenId && (() => {
        const sel = tokens.find((t) => t.token_id === selectedTokenId);
        if (!sel) return null;
        const baseUrl = typeof window !== "undefined" ? window.location.origin : "https://piloci.opencourse.kr";
        const placeholder = "<여기에_토큰_붙여넣기>";
        const detailConfigs = buildMcpConfigs(placeholder, baseUrl);

        return (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">{t.tokenManager.mcpConfigFor} &ldquo;{sel.name}&rdquo;</p>
              <Button variant="ghost" size="sm" onClick={() => setSelectedTokenId(null)}>
                <ChevronUp className="size-4" />
              </Button>
            </div>
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              토큰은 발급 시에만 확인할 수 있습니다. 아래 설정에서 <code className="font-mono">&lt;여기에_토큰_붙여넣기&gt;</code> 부분을 발급받은 토큰으로 교체하세요.
            </div>
            <Card className="border bg-card shadow-sm">
              <CardContent className="p-4">
                <Tabs defaultValue="claude-desktop">
                  <TabsList>
                    <TabsTrigger value="claude-desktop">Claude Desktop</TabsTrigger>
                    <TabsTrigger value="claude-code">Claude Code</TabsTrigger>
                    <TabsTrigger value="opencode">OpenCode</TabsTrigger>
                    <TabsTrigger value="cursor">Cursor</TabsTrigger>
                  </TabsList>

                  <TabsContent value="claude-desktop" className="space-y-2 pt-3">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono">~/Library/Application Support/Claude/claude_desktop_config.json</span>
                    </div>
                    <CopyBlock value={detailConfigs.claude} />
                  </TabsContent>

                  <TabsContent value="claude-code" className="space-y-2 pt-3">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono">~/.claude.json</span>
                      <span className="text-border">|</span>
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono">.mcp.json</span>
                    </div>
                    <CopyBlock value={detailConfigs.claude} />
                  </TabsContent>

                  <TabsContent value="opencode" className="space-y-2 pt-3">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono">opencode.json</span>
                    </div>
                    <CopyBlock value={detailConfigs.opencode} />
                  </TabsContent>

                  <TabsContent value="cursor" className="space-y-2 pt-3">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono">~/.cursor/mcp.json</span>
                    </div>
                    <CopyBlock value={detailConfigs.claude} />
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          </div>
        );
      })()}
    </div>
  );
}
