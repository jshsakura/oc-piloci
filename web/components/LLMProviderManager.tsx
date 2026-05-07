"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Pencil, Power, PowerOff } from "lucide-react";
import { api } from "@/lib/api";
import type { LLMProvider } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

type FormState = {
  name: string;
  base_url: string;
  model: string;
  api_key: string;
  priority: number;
  enabled: boolean;
};

const EMPTY: FormState = {
  name: "",
  base_url: "",
  model: "",
  api_key: "",
  priority: 100,
  enabled: true,
};

function ProviderForm({
  initial,
  editing,
  onSubmit,
  onCancel,
  pending,
  error,
}: {
  initial: FormState;
  editing: boolean;
  onSubmit: (s: FormState) => void;
  onCancel: () => void;
  pending: boolean;
  error: string;
}) {
  const [form, setForm] = useState<FormState>(initial);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(form);
      }}
      className="space-y-3"
    >
      <div className="space-y-1.5">
        <Label htmlFor="llm-name">이름 *</Label>
        <Input
          id="llm-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Z.AI"
          maxLength={100}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="llm-url">Base URL *</Label>
        <Input
          id="llm-url"
          value={form.base_url}
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          placeholder="https://api.z.ai/api/paas/v4"
          maxLength={500}
        />
        <p className="text-xs text-muted-foreground">
          OpenAI-compatible 엔드포인트의 베이스. <code>/v1/chat/completions</code>는 자동 보정됨.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="llm-model">모델 *</Label>
        <Input
          id="llm-model"
          value={form.model}
          onChange={(e) => setForm({ ...form, model: e.target.value })}
          placeholder="glm-4.5"
          maxLength={100}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="llm-key">API 키 {editing && <span className="text-xs text-muted-foreground">(비워두면 기존 키 유지)</span>} {!editing && "*"}</Label>
        <Input
          id="llm-key"
          type="password"
          value={form.api_key}
          onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          placeholder="sk-..."
          maxLength={500}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="llm-priority">우선순위</Label>
          <Input
            id="llm-priority"
            type="number"
            min={0}
            max={1000}
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: Number(e.target.value) || 0 })}
          />
          <p className="text-xs text-muted-foreground">낮을수록 먼저 시도</p>
        </div>
        <div className="flex items-end">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="size-4"
            />
            활성화
          </label>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          취소
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? "저장 중..." : editing ? "저장" : "추가"}
        </Button>
      </div>
    </form>
  );
}

function ProviderRow({
  provider,
  onEdit,
  onToggle,
  onDelete,
  toggling,
}: {
  provider: LLMProvider;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  toggling: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border bg-card p-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{provider.name}</span>
          <Badge variant={provider.enabled ? "default" : "secondary"} className="text-xs">
            {provider.enabled ? "활성" : "비활성"}
          </Badge>
          <Badge variant="outline" className="text-xs">우선순위 {provider.priority}</Badge>
        </div>
        <p className="break-all font-mono text-xs text-muted-foreground">
          {provider.base_url}
        </p>
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>모델: <code className="font-mono">{provider.model}</code></span>
          {provider.api_key_masked && (
            <span>키: <code className="font-mono">{provider.api_key_masked}</code></span>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <Button
          size="icon"
          variant="ghost"
          className="size-8"
          onClick={onToggle}
          disabled={toggling}
          aria-label={provider.enabled ? "비활성화" : "활성화"}
        >
          {provider.enabled ? <Power className="size-3.5" /> : <PowerOff className="size-3.5 text-muted-foreground" />}
        </Button>
        <Button size="icon" variant="ghost" className="size-8" onClick={onEdit} aria-label="편집">
          <Pencil className="size-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-8 text-muted-foreground hover:text-destructive"
          onClick={onDelete}
          aria-label="삭제"
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

export function LLMProviderManager() {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<LLMProvider | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<LLMProvider | null>(null);
  const [formError, setFormError] = useState("");

  const { data: providers = [], isLoading, isError } = useQuery({
    queryKey: ["llm-providers"],
    queryFn: api.listLLMProviders,
  });

  const createMutation = useMutation({
    mutationFn: api.createLLMProvider,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      setShowAdd(false);
      setFormError("");
    },
    onError: (err: unknown) => {
      setFormError(err instanceof Error ? err.message : "추가에 실패했습니다");
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<LLMProvider> & { api_key?: string } }) =>
      api.updateLLMProvider(id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      setEditing(null);
      setFormError("");
    },
    onError: (err: unknown) => {
      setFormError(err instanceof Error ? err.message : "저장에 실패했습니다");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteLLMProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      setConfirmDelete(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateLLMProvider(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
    },
  });

  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">외부 LLM 백업</h3>
            <p className="text-xs text-muted-foreground">
              로컬 Gemma가 막히면 우선순위 순으로 외부 OpenAI-compatible 모델로 폴백합니다.
            </p>
          </div>
          <Button
            size="sm"
            onClick={() => {
              setShowAdd(true);
              setFormError("");
            }}
          >
            <Plus className="mr-1 size-4" /> 추가
          </Button>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="text-sm text-destructive">목록을 불러오지 못했습니다.</p>
        ) : providers.length === 0 ? (
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            등록된 외부 LLM이 없습니다. Gemma만 사용 중.
          </p>
        ) : (
          <div className="space-y-2">
            {providers.map((p) => (
              <ProviderRow
                key={p.id}
                provider={p}
                onEdit={() => {
                  setEditing(p);
                  setFormError("");
                }}
                onToggle={() => toggleMutation.mutate({ id: p.id, enabled: !p.enabled })}
                onDelete={() => setConfirmDelete(p)}
                toggling={toggleMutation.isPending}
              />
            ))}
          </div>
        )}

        <Dialog
          open={showAdd}
          onOpenChange={(open) => {
            setShowAdd(open);
            if (!open) setFormError("");
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>외부 LLM 추가</DialogTitle>
            </DialogHeader>
            <ProviderForm
              initial={EMPTY}
              editing={false}
              pending={createMutation.isPending}
              error={formError}
              onCancel={() => {
                setShowAdd(false);
                setFormError("");
              }}
              onSubmit={(form) => {
                if (!form.name || !form.base_url || !form.model || !form.api_key) {
                  setFormError("이름·Base URL·모델·API 키 모두 필요합니다");
                  return;
                }
                createMutation.mutate(form);
              }}
            />
          </DialogContent>
        </Dialog>

        <Dialog
          open={!!editing}
          onOpenChange={(open) => {
            if (!open) {
              setEditing(null);
              setFormError("");
            }
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>외부 LLM 편집</DialogTitle>
            </DialogHeader>
            {editing && (
              <ProviderForm
                initial={{
                  name: editing.name,
                  base_url: editing.base_url,
                  model: editing.model,
                  api_key: "",
                  priority: editing.priority,
                  enabled: editing.enabled,
                }}
                editing
                pending={updateMutation.isPending}
                error={formError}
                onCancel={() => {
                  setEditing(null);
                  setFormError("");
                }}
                onSubmit={(form) => {
                  const patch: Partial<LLMProvider> & { api_key?: string } = {
                    name: form.name,
                    base_url: form.base_url,
                    model: form.model,
                    enabled: form.enabled,
                    priority: form.priority,
                  };
                  if (form.api_key) patch.api_key = form.api_key;
                  updateMutation.mutate({ id: editing.id, patch });
                }}
              />
            )}
          </DialogContent>
        </Dialog>

        <ConfirmDialog
          open={!!confirmDelete}
          onOpenChange={(open) => {
            if (!open) setConfirmDelete(null);
          }}
          title={`"${confirmDelete?.name}" 제거`}
          description="이 외부 LLM 백업을 목록에서 제거합니다. API 키도 함께 삭제됩니다."
          confirmLabel="제거"
          variant="destructive"
          pending={deleteMutation.isPending}
          onConfirm={() => {
            if (confirmDelete) deleteMutation.mutate(confirmDelete.id);
          }}
        />
      </CardContent>
    </Card>
  );
}
