"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, RefreshCcw } from "lucide-react";
import AppShell from "@/components/AppShell";
import { ProjectCard } from "@/components/ProjectCard";
import { DashboardSummaryPanels } from "@/components/DashboardSummaryPanels";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import RoutePending from "@/components/RoutePending";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

export default function DashboardPage() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();
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
    enabled: !!user,
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

  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) router.replace("/login");
  }, [hasHydrated, isBootstrapping, router, user]);

  if (!hasHydrated || isBootstrapping) {
    return (
      <AppShell>
        <RoutePending title={t.dashboard.pending.title} description={t.dashboard.pending.desc} />
      </AppShell>
    );
  }

  if (!user) {
    return (
      <RoutePending
        fullScreen
        title={t.dashboard.redirect.title}
        description={t.dashboard.redirect.desc}
      />
    );
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!newSlug.trim() || !newName.trim()) {
      setFormError(t.dashboard.validation.slugAndNameRequired);
      return;
    }
    createMutation.mutate();
  };

  const projectCount = projects?.length ?? 0;
  const totalMemories = projects?.reduce((sum, p) => sum + p.memory_count, 0) ?? 0;
  const totalKnacks = projects?.reduce((sum, p) => sum + (p.instinct_count ?? 0), 0) ?? 0;

  return (
    <AppShell>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t.dashboard.title}</h1>
          <p className="text-sm text-muted-foreground">{t.dashboard.subtitle}</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm">
              <FolderPlus className="mr-2 size-4" />
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

      {/* Activity + recent content panels — direct dashboard surface so the
          user sees living data without drilling into projects. */}
      <DashboardSummaryPanels
        totalMemories={totalMemories}
        totalKnacks={totalKnacks}
        projectCount={projectCount}
      />

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
    </AppShell>
  );
}
