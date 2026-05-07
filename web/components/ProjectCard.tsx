"use client";

import { useState } from "react";
import { ArrowRight, Pencil, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ProjectCardProps {
  project: Project;
  onOpen: (project: Project) => void;
}

export function ProjectCard({ project, onOpen }: ProjectCardProps) {
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [error, setError] = useState("");

  const updateMutation = useMutation({
    mutationFn: () =>
      api.updateProject(project.id, {
        name: name.trim(),
        description: description.trim() ? description.trim() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setEditOpen(false);
      setError("");
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "저장에 실패했습니다");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteProject(project.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setConfirmOpen(false);
    },
  });

  const openEdit = () => {
    setName(project.name);
    setDescription(project.description ?? "");
    setError("");
    setEditOpen(true);
  };

  return (
    <Card className="group transition-shadow hover:shadow-md">
      <CardContent className="p-5">
        <div className="mb-3 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate font-semibold">{project.name}</h3>
            <p className="truncate text-sm text-muted-foreground">
              {project.description || "프로젝트 워크스페이스"}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-0.5 opacity-60 transition-opacity group-hover:opacity-100">
            <Button
              size="icon"
              variant="ghost"
              className="size-8"
              onClick={openEdit}
              aria-label="프로젝트 편집"
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-8 text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmOpen(true)}
              aria-label="프로젝트 삭제"
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          <Badge variant="secondary">{project.slug}</Badge>
          <Badge variant="outline">{project.memory_count} 메모리</Badge>
        </div>

        <div className="flex items-center justify-between border-t pt-3">
          <span className="text-xs text-muted-foreground">
            {new Date(project.created_at).toLocaleDateString("ko-KR")}
          </span>
          <Button size="sm" onClick={() => onOpen(project)}>
            열기
            <ArrowRight className="ml-1 size-3" />
          </Button>
        </div>
      </CardContent>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>프로젝트 편집</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setError("");
              if (!name.trim()) {
                setError("이름은 비워둘 수 없습니다");
                return;
              }
              updateMutation.mutate();
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label>슬러그</Label>
              <Input value={project.slug} disabled />
              <p className="text-xs text-muted-foreground">
                슬러그는 메모리·토큰 매핑 키라 변경할 수 없습니다.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-name">이름 *</Label>
              <Input
                id="edit-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-desc">설명</Label>
              <Input
                id="edit-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={2000}
                placeholder="프로젝트 설명"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditOpen(false)}
              >
                취소
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "저장 중..." : "저장"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`"${project.name}" 삭제`}
        description="이 프로젝트와 연결된 모든 메모리·노트가 함께 사라집니다. 되돌릴 수 없습니다."
        confirmLabel="삭제"
        variant="destructive"
        pending={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
      />
    </Card>
  );
}
