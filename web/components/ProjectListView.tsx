"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, RefreshCcw } from "lucide-react";
import { ProjectCard } from "@/components/ProjectCard";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

export function ProjectListView() {
  const router = useRouter();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [formError, setFormError] = useState("");

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
      setFormError(err instanceof Error ? err.message : t.dashboard.validation.createFailed);
    },
  });

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!newSlug.trim() || !newName.trim()) {
      setFormError(t.dashboard.validation.slugAndNameRequired);
      return;
    }
    createMutation.mutate();
  };

  return (
    <>
      <div className="pi-page-hero flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="pi-eyebrow">{t.projects.eyebrow}</p>
          <h1 className="pi-title mt-2">{t.appShell.nav.projects}</h1>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="rounded-full">
              <FolderPlus className="me-2 size-4" />
              {t.dashboard.newProject}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t.dashboard.createTitle}</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="slug">{t.dashboard.slugLabel}</Label>
                <Input
                  id="slug"
                  value={newSlug}
                  onChange={(e) => setNewSlug(e.target.value)}
                  placeholder="my-project"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">{t.dashboard.nameLabel}</Label>
                <Input
                  id="name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="My Project"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="desc">{t.dashboard.descLabel}</Label>
                <Input
                  id="desc"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder={t.dashboard.descPlaceholder}
                />
              </div>
              {formError && <p className="text-sm text-destructive">{formError}</p>}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  {t.dashboard.cancel}
                </Button>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t.dashboard.creating : t.dashboard.create}
                </Button>
              </div>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="mt-6">
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
              <p className="text-sm text-muted-foreground">{t.dashboard.error.title}</p>
              <Button variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey: ["projects"] })}>
                {t.dashboard.error.retry}
              </Button>
            </CardContent>
          </Card>
        ) : projects?.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-4 py-12">
              <FolderPlus className="size-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{t.dashboard.empty.title}</p>
              <Button onClick={() => setOpen(true)}>{t.dashboard.empty.create}</Button>
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
    </>
  );
}
