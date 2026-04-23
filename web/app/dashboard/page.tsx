'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ProjectList } from '@/components/ProjectList';
import { useAuthStore } from '@/lib/auth';
import { api } from '@/lib/api';
import { Project } from '@/lib/types';
import { Card, CardHeader, CardTitle, CardContent } from '@/engine/components/ui/card';
import { Button } from '@/engine/components/ui/button';
import { Input } from '@/engine/components/ui/input';
import { Skeleton } from '@/engine/components/ui/skeleton';
import { TopBar } from '@/engine/components/patterns/top-bar';

function SkeletonCard() {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-start justify-between gap-2 mb-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
        <Skeleton className="h-3 w-24 mb-3" />
        <Skeleton className="h-3 w-20" />
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const queryClient = useQueryClient();

  const [showNewForm, setShowNewForm] = useState(false);
  const [newSlug, setNewSlug] = useState('');
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [formError, setFormError] = useState('');

  useEffect(() => {
    if (user === null) {
      router.replace('/login');
    }
  }, [user, router]);

  if (user === null) {
    return null;
  }

  const { data: projects, isLoading, isError } = useQuery({
    queryKey: ['projects'],
    queryFn: api.listProjects,
  });

  const createMutation = useMutation({
    mutationFn: () => api.createProject(newSlug, newName, newDescription || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setShowNewForm(false);
      setNewSlug('');
      setNewName('');
      setNewDescription('');
      setFormError('');
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : '프로젝트 생성에 실패했습니다.';
      setFormError(msg);
    },
  });

  const handleProjectSelect = (project: Project) => {
    router.push('/projects/?slug=' + project.slug);
  };

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    if (!newSlug.trim() || !newName.trim()) {
      setFormError('슬러그와 이름을 모두 입력해주세요.');
      return;
    }
    createMutation.mutate();
  };

  const handleLogout = () => {
    logout();
    router.replace('/login');
  };

  return (
    <div className="min-h-screen bg-surface-page">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <TopBar
          logo={
            <div>
              <h1 className="text-2xl font-bold text-text-primary">
                안녕하세요, {user.email}님
              </h1>
              <p className="text-sm text-text-secondary mt-1">piLoci 메모리 대시보드</p>
            </div>
          }
          actions={
            <Button variant="outline" size="sm" onClick={handleLogout}>
              로그아웃
            </Button>
          }
        />

        {/* Projects Section */}
        <div className="px-6 pb-8">
          <Card>
            <CardHeader className="border-b">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg font-semibold">프로젝트</CardTitle>
                <Button
                  variant={showNewForm ? 'outline' : 'default'}
                  size="sm"
                  onClick={() => {
                    setShowNewForm((v) => !v);
                    setFormError('');
                  }}
                >
                  {showNewForm ? '취소' : '+ 새 프로젝트'}
                </Button>
              </div>
            </CardHeader>

            <CardContent>
              {/* New Project Form */}
              {showNewForm && (
                <form
                  onSubmit={handleCreateSubmit}
                  className="mb-6 p-4 rounded-xl border border-border bg-surface-page"
                >
                  <h3 className="text-sm font-semibold text-text-primary mb-4">새 프로젝트 만들기</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
                    <div>
                      <label className="block text-xs text-text-secondary mb-1">슬러그 *</label>
                      <Input
                        type="text"
                        value={newSlug}
                        onChange={(e) => setNewSlug(e.target.value)}
                        placeholder="my-project"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-text-secondary mb-1">이름 *</label>
                      <Input
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="프로젝트 이름"
                      />
                    </div>
                  </div>
                  <div className="mb-3">
                    <label className="block text-xs text-text-secondary mb-1">설명 (선택)</label>
                    <Input
                      type="text"
                      value={newDescription}
                      onChange={(e) => setNewDescription(e.target.value)}
                      placeholder="프로젝트 설명"
                    />
                  </div>
                  {formError && (
                    <p className="text-xs text-destructive mb-3">{formError}</p>
                  )}
                  <Button
                    type="submit"
                    disabled={createMutation.isPending}
                    size="sm"
                  >
                    {createMutation.isPending ? '생성 중...' : '프로젝트 만들기'}
                  </Button>
                </form>
              )}

              {/* Content */}
              {isLoading ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  <SkeletonCard />
                  <SkeletonCard />
                  <SkeletonCard />
                </div>
              ) : isError ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <p className="text-destructive text-sm">데이터를 불러오지 못했습니다. 새로고침해주세요.</p>
                  <Button
                    variant="brandGhost"
                    size="xs"
                    className="mt-3"
                    onClick={() => queryClient.invalidateQueries({ queryKey: ['projects'] })}
                  >
                    다시 시도
                  </Button>
                </div>
              ) : (
                <ProjectList projects={projects ?? []} onSelect={handleProjectSelect} />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
