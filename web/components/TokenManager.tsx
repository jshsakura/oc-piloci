"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Copy, Trash2, Check } from "lucide-react";
import { api } from "@/lib/api";
import type { ApiToken, CreatedToken, Project } from "@/lib/types";
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

// ---------------------------------------------------------------------------
// CopyBlock — code block with copy button
// ---------------------------------------------------------------------------

function CopyBlock({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-1.5">
      {label && <p className="text-xs text-muted-foreground">{label}</p>}
      <div className="relative rounded-md border bg-muted">
        <pre className="overflow-x-auto p-3 pr-12 text-xs leading-relaxed">{value}</pre>
        <Button
          size="icon"
          variant="ghost"
          className="absolute right-1 top-1 size-7 text-muted-foreground hover:text-foreground"
          onClick={handleCopy}
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SetupDialog — shown once after project-scoped token is created
// ---------------------------------------------------------------------------

function SetupDialog({ data, onClose }: { data: CreatedToken; onClose: () => void }) {
  const hasSetup = !!data.setup;
  const mcpJson = data.setup ? JSON.stringify(data.setup.mcp_config, null, 2) : null;
  const hookJson = data.setup ? JSON.stringify(data.setup.hook_config, null, 2) : null;

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>토큰 발급 완료</DialogTitle>
        </DialogHeader>

        {hasSetup ? (
          <Tabs defaultValue="token">
            <TabsList className="w-full">
              <TabsTrigger value="token" className="flex-1">토큰</TabsTrigger>
              <TabsTrigger value="mcp" className="flex-1">MCP 서버</TabsTrigger>
              <TabsTrigger value="hook" className="flex-1">Stop 훅</TabsTrigger>
            </TabsList>

            {/* ── Tab 1: Token ── */}
            <TabsContent value="token" className="space-y-3 pt-1">
              <p className="text-sm text-destructive">이 토큰은 다시 볼 수 없습니다. 지금 복사하세요.</p>
              <CopyBlock value={data.token} />
            </TabsContent>

            {/* ── Tab 2: MCP Server ── */}
            <TabsContent value="mcp" className="space-y-3 pt-1">
              <p className="text-sm text-muted-foreground">
                <code className="rounded bg-muted px-1 py-0.5 text-xs">~/.claude/mcp.json</code>에
                아래 내용을 붙여넣으세요. 기존 파일이 있으면 <code className="rounded bg-muted px-1 py-0.5 text-xs">mcpServers</code> 키만 병합합니다.
              </p>
              <CopyBlock value={mcpJson!} />
              <p className="text-xs text-muted-foreground">
                설정 후 Claude Code를 재시작하면 <code className="rounded bg-muted px-1 py-0.5 text-xs">memory</code>,{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">recall</code>,{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">recommend</code> 툴이 자동으로 활성화됩니다.
              </p>
            </TabsContent>

            {/* ── Tab 3: Stop Hook ── */}
            <TabsContent value="hook" className="space-y-3 pt-1">
              <p className="text-sm text-muted-foreground">
                <code className="rounded bg-muted px-1 py-0.5 text-xs">~/.claude/settings.json</code>의{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">hooks</code> 키에 아래를 병합하세요.
                세션이 끝날 때마다 piLoci가 패턴을 자동으로 학습합니다.
              </p>
              <CopyBlock value={hookJson!} />
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                <strong>조건:</strong> 세션 메시지가 5개 이상일 때만 분석합니다. python3과 인터넷 연결 없이 로컬에서만 동작합니다.
              </div>
            </TabsContent>
          </Tabs>
        ) : (
          /* user-scope token — simple view */
          <div className="space-y-3">
            <p className="text-sm text-destructive">이 토큰은 다시 볼 수 없습니다. 지금 복사하세요.</p>
            <CopyBlock value={data.token} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// TokenManager
// ---------------------------------------------------------------------------

export function TokenManager() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [formName, setFormName] = useState("");
  const [formScope, setFormScope] = useState<"user" | "project">("user");
  const [formProjectId, setFormProjectId] = useState("");
  const [createdToken, setCreatedToken] = useState<CreatedToken | null>(null);

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
    }: {
      name: string;
      scope: "user" | "project";
      project_id?: string;
    }) => api.createToken(name, scope, project_id) as Promise<CreatedToken>,
    onSuccess: (data) => {
      setCreatedToken(data);
      queryClient.invalidateQueries({ queryKey: ["tokens"] });
      setShowCreate(false);
      setFormName("");
      setFormScope("user");
      setFormProjectId("");
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.revokeToken(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tokens"] }),
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) return;
    createMutation.mutate({
      name: formName.trim(),
      scope: formScope,
      project_id: formScope === "project" && formProjectId ? formProjectId : undefined,
    });
  };

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString("ko-KR", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">API 토큰으로 외부 클라이언트에서 piLoci에 접근합니다</p>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1 size-4" /> 발급
        </Button>
      </div>

      {createdToken && (
        <SetupDialog data={createdToken} onClose={() => setCreatedToken(null)} />
      )}

      {showCreate && (
        <Card>
          <CardContent className="p-4">
            <form onSubmit={handleCreate} className="space-y-3">
              <div className="space-y-1.5">
                <Label>토큰 이름</Label>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="예: Claude Code"
                />
              </div>
              <div className="space-y-1.5">
                <Label>범위</Label>
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
                    <SelectItem value="user">사용자 전체</SelectItem>
                    <SelectItem value="project">프로젝트 (MCP + Stop 훅 설정 자동 생성)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {formScope === "project" && (
                <div className="space-y-1.5">
                  <Label>프로젝트</Label>
                  <Select value={formProjectId} onValueChange={setFormProjectId}>
                    <SelectTrigger>
                      <SelectValue placeholder="선택" />
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
              {createMutation.error && (
                <p className="text-sm text-destructive">
                  {(createMutation.error as Error).message}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
                  취소
                </Button>
                <Button
                  type="submit"
                  disabled={createMutation.isPending || !formName.trim()}
                >
                  {createMutation.isPending ? "발급 중..." : "발급"}
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
            발급된 토큰이 없습니다
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>범위</TableHead>
                <TableHead>발급일</TableHead>
                <TableHead>마지막 사용</TableHead>
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((token) => {
                const project = token.project_id
                  ? projects.find((p) => p.id === token.project_id)
                  : undefined;
                return (
                  <TableRow key={token.token_id}>
                    <TableCell className="font-medium">
                      {token.name}
                      {project && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          ({project.slug})
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={token.scope === "user" ? "default" : "secondary"}>
                        {token.scope}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(token.created_at)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {token.last_used_at ? formatDate(token.last_used_at) : "-"}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => {
                          if (window.confirm(`"${token.name}" 토큰을 폐기하시겠습니까?`)) {
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
    </div>
  );
}
