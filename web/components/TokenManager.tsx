"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Copy, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { ApiToken, Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

export function TokenManager() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [formName, setFormName] = useState("");
  const [formScope, setFormScope] = useState<"user" | "project">("user");
  const [formProjectId, setFormProjectId] = useState("");
  const [newToken, setNewToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: tokens = [], isLoading } = useQuery<ApiToken[]>({
    queryKey: ["tokens"],
    queryFn: () => api.listTokens(),
  });

  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
  });

  const createMutation = useMutation({
    mutationFn: ({ name, scope, project_id }: { name: string; scope: "user" | "project"; project_id?: string }) =>
      api.createToken(name, scope, project_id) as Promise<{ token: string }>,
    onSuccess: (data) => {
      setNewToken(data.token);
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

  const handleCopy = async () => {
    if (!newToken) return;
    await navigator.clipboard.writeText(newToken);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "short", day: "numeric" });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">API 토큰으로 외부 클라이언트에서 piLoci에 접근합니다</p>
        <Button size="sm" onClick={() => setShowCreate(true)}>
          <Plus className="mr-1 size-4" /> 발급
        </Button>
      </div>

      {newToken && (
        <Dialog open onOpenChange={() => setNewToken(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>토큰이 발급되었습니다</DialogTitle>
            </DialogHeader>
            <p className="text-sm text-destructive">이 토큰은 다시 볼 수 없습니다. 지금 복사하세요.</p>
            <div className="flex items-center gap-2 rounded-md border bg-muted p-3">
              <code className="flex-1 break-all font-mono text-xs">{newToken}</code>
              <Button size="sm" variant="outline" onClick={handleCopy}>
                <Copy className="mr-1 size-3" />
                {copied ? "복사됨" : "복사"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {showCreate && (
        <Card>
          <CardContent className="p-4">
            <form onSubmit={handleCreate} className="space-y-3">
              <div className="space-y-1.5">
                <Label>토큰 이름</Label>
                <Input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="예: Claude Code" />
              </div>
              <div className="space-y-1.5">
                <Label>범위</Label>
                <Select value={formScope} onValueChange={(v: "user" | "project") => { setFormScope(v); if (v === "user") setFormProjectId(""); }}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="user">사용자 전체</SelectItem>
                    <SelectItem value="project">프로젝트</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {formScope === "project" && (
                <div className="space-y-1.5">
                  <Label>프로젝트</Label>
                  <Select value={formProjectId} onValueChange={setFormProjectId}>
                    <SelectTrigger><SelectValue placeholder="선택" /></SelectTrigger>
                    <SelectContent>
                      {projects.map((p) => (
                        <SelectItem key={p.id} value={p.id}>{p.name} ({p.slug})</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              {createMutation.error && (
                <p className="text-sm text-destructive">{(createMutation.error as Error).message}</p>
              )}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>취소</Button>
                <Button type="submit" disabled={createMutation.isPending || !formName.trim()}>
                  {createMutation.isPending ? "발급 중..." : "발급"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
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
                const project = token.project_id ? projects.find((p) => p.id === token.project_id) : undefined;
                return (
                  <TableRow key={token.token_id}>
                    <TableCell className="font-medium">
                      {token.name}
                      {project && <span className="ml-2 text-xs text-muted-foreground">({project.slug})</span>}
                    </TableCell>
                    <TableCell>
                      <Badge variant={token.scope === "user" ? "default" : "secondary"}>
                        {token.scope}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{formatDate(token.created_at)}</TableCell>
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
