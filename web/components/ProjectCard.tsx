"use client";

import { useState } from "react";
import { ArrowRight, Pencil, Trash2, Brain, Lightbulb, Activity } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
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
  const { t, locale } = useTranslation();
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
      setError(err instanceof Error ? err.message : t.projects.editSaveFailed);
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
              {project.description || t.projectCard.workspace}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-0.5 opacity-60 transition-opacity group-hover:opacity-100">
            <Button
              size="icon"
              variant="ghost"
              className="size-8"
              onClick={openEdit}
              aria-label={t.projects.editAria}
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="size-8 text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmOpen(true)}
              aria-label={t.projects.deleteAria}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          <Badge variant="secondary">{project.slug}</Badge>
          <Badge variant="outline" className="inline-flex items-center gap-1">
            <Brain className="size-3" /> {project.memory_count} {t.projects.cardMemories}
          </Badge>
          <Badge variant="outline" className="inline-flex items-center gap-1">
            <Lightbulb className="size-3" /> {project.instinct_count ?? 0} {t.projects.cardKnacks}
          </Badge>
        </div>

        <div className="flex items-center justify-between border-t pt-3">
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Activity className="size-3" />
            {project.last_active_at
              ? new Date(project.last_active_at).toLocaleDateString(locale)
              : t.projects.neverActive}
          </span>
          <Button size="sm" onClick={() => onOpen(project)}>
            {t.projects.openButton}
            <ArrowRight className="ml-1 size-3" />
          </Button>
        </div>
      </CardContent>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.projects.editTitle}</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setError("");
              if (!name.trim()) {
                setError(t.projects.editNameRequired);
                return;
              }
              updateMutation.mutate();
            }}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label>{t.projects.editSlugLabel}</Label>
              <Input value={project.slug} disabled />
              <p className="text-xs text-muted-foreground">{t.projects.editSlugHelp}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-name">{t.projects.editNameLabel}</Label>
              <Input
                id="edit-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={200}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-desc">{t.projects.editDescLabel}</Label>
              <Input
                id="edit-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={2000}
                placeholder={t.projects.editDescPlaceholder}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditOpen(false)}
              >
                {t.projects.editCancel}
              </Button>
              <Button type="submit" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? t.projects.editSaving : t.projects.editSave}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`"${project.name}" ${t.projects.deleteTitle}`}
        description={t.projects.deleteDesc}
        confirmLabel={t.projects.deleteConfirm}
        variant="destructive"
        pending={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
      />
    </Card>
  );
}
