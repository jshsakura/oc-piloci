"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, RefreshCcw } from "lucide-react";
import AppShell from "@/components/AppShell";
import { ProjectCard } from "@/components/ProjectCard";
import { useAuthStore } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

export default function DashboardPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [formError, setFormError] = useState("");

  useEffect(() => {
    if (!user) router.replace("/login");
  }, [router, user]);

  if (!user) return null;

  const { data: projects, isLoading, isError } = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });

  const createMutation = useMutation({
    mutationFn: () => api.createProject(newSlug, newName, newDescription || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setOpen(false);
      setNewSlug("");
      setNewName("");
      setNewDescription("");
      setFormError("");
    },
    onError: (err: unknown) => {
      setFormError(err instanceof Error ? err.message : "프로젝트 생성에 실패했습니다");
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!newSlug.trim() || !newName.trim()) {
      setFormError("슬러그와 이름을 모두 입력해주세요");
      return;
    }
    createMutation.mutate();
  };

  const projectCount = projects?.length ?? 0;
  const totalMemories = projects?.reduce((sum, p) => sum + p.memory_count, 0) ?? 0;

  return (
    <AppShell>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">대시보드</h1>
          <p className="text-sm text-muted-foreground">프로젝트를 관리하고 워크스페이스에 접속하세요</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <FolderPlus className="mr-2 size-4" />
              새 프로젝트
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>새 프로젝트 만들기</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="slug">슬러그 *</Label>
                <Input
                  id="slug"
                  value={newSlug}
                  onChange={(e) => setNewSlug(e.target.value)}
                  placeholder="my-project"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">이름 *</Label>
                <Input
                  id="name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="My Project"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="desc">설명</Label>
                <Input
                  id="desc"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="프로젝트 설명"
                />
              </div>
              {formError && <p className="text-sm text-destructive">{formError}</p>}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  취소
                </Button>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? "생성 중..." : "생성"}
                </Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Stats */}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">프로젝트</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{projectCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">총 메모리</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{totalMemories}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">상태</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{isLoading ? "동기화 중" : "준비"}</p>
          </CardContent>
        </Card>
      </div>

      {/* Projects */}
      <div className="mt-8">
        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="p-6">
                  <Skeleton className="mb-3 h-5 w-32" />
                  <Skeleton className="mb-2 h-4 w-full" />
                  <Skeleton className="h-4 w-24" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : isError ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-4 py-12">
              <RefreshCcw className="size-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">프로젝트를 불러오지 못했습니다</p>
              <Button variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey: ["projects"] })}>
                재시도
              </Button>
            </CardContent>
          </Card>
        ) : projects?.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-4 py-12">
              <FolderPlus className="size-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">아직 프로젝트가 없습니다</p>
              <Button onClick={() => setOpen(true)}>프로젝트 만들기</Button>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects?.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onOpen={(p: Project) => router.push(`/projects/?slug=${p.slug}`)}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
