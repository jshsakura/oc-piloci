"use client";

import { ArrowRight, Trash2 } from "lucide-react";
import Link from "next/link";
import type { Project } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface ProjectCardProps {
  project: Project;
  onOpen: (project: Project) => void;
}

export function ProjectCard({ project, onOpen }: ProjectCardProps) {
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
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          <Badge variant="secondary">{project.slug}</Badge>
          <Badge variant="outline">{project.memory_count} 메모리</Badge>
        </div>

        <div className="flex items-center justify-between border-t pt-3">
          <span className="text-xs text-muted-foreground">
            {new Date(project.created_at).toLocaleDateString("ko-KR")}
          </span>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => onOpen(project)}>
              열기
              <ArrowRight className="ml-1 size-3" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
