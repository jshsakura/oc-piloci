'use client';

import { Project } from '@/lib/types';
import { Card, CardHeader, CardTitle, CardContent } from '@/engine/components/ui/card';
import { Badge } from '@/engine/components/ui/badge';
import { EmptyState } from '@/engine/components/patterns/empty-state';

interface ProjectListProps {
  projects: Project[];
  onSelect: (project: Project) => void;
}

function FolderIcon() {
  return (
    <svg
      className="size-4"
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.5}
        d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
      />
    </svg>
  );
}

export function ProjectList({ projects, onSelect }: ProjectListProps) {
  if (projects.length === 0) {
    return (
      <EmptyState
        title="프로젝트가 없습니다"
        description="첫 프로젝트를 만들어보세요."
      />
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {projects.map((project) => (
        <button
          key={project.id}
          onClick={() => onSelect(project)}
          className="text-left focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 rounded-xl"
        >
          <Card className="hover:border-brand transition-colors h-full">
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="font-semibold text-text-primary truncate">
                  {project.name}
                </CardTitle>
                <Badge variant="secondary" className="flex-shrink-0">
                  {project.memory_count} 메모리
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-text-secondary mb-2 font-mono">{project.slug}</p>
              {project.description && (
                <p className="text-sm text-text-secondary mb-2 line-clamp-2">{project.description}</p>
              )}
              <p className="text-xs text-text-tertiary">
                {new Date(project.created_at).toLocaleDateString('ko-KR')}
              </p>
            </CardContent>
          </Card>
        </button>
      ))}
    </div>
  );
}
