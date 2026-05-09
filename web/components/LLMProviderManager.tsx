"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Pencil, Power, PowerOff } from "lucide-react";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
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
  const { t } = useTranslation();
  const f = t.llm.form;
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
        <Label htmlFor="llm-name">{f.nameLabel}</Label>
        <Input
          id="llm-name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Z.AI"
          maxLength={100}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="llm-url">{f.baseUrlLabel}</Label>
        <Input
          id="llm-url"
          value={form.base_url}
          onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          placeholder="https://api.z.ai/api/paas/v4"
          maxLength={500}
        />
        <p className="text-xs text-muted-foreground">{f.baseUrlHelp}</p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="llm-model">{f.modelLabel}</Label>
        <Input
          id="llm-model"
          value={form.model}
          onChange={(e) => setForm({ ...form, model: e.target.value })}
          placeholder="glm-4.5"
          maxLength={100}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="llm-key">
          {f.apiKeyLabel}{" "}
          {editing && (
            <span className="text-xs text-muted-foreground">({f.apiKeyEditNote})</span>
          )}
          {!editing && " *"}
        </Label>
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
          <Label htmlFor="llm-priority">{f.priorityLabel}</Label>
          <Input
            id="llm-priority"
            type="number"
            min={0}
            max={1000}
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: Number(e.target.value) || 0 })}
          />
          <p className="text-xs text-muted-foreground">{f.priorityHelp}</p>
        </div>
        <div className="flex items-end">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="size-4"
            />
            {f.enabledLabel}
          </label>
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {f.cancel}
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? f.saving : editing ? f.save : f.addAction}
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
  const { t } = useTranslation();
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border bg-card p-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{provider.name}</span>
          <Badge variant={provider.enabled ? "default" : "secondary"} className="text-xs">
            {provider.enabled ? t.llm.enabled : t.llm.disabled}
          </Badge>
          <Badge variant="outline" className="text-xs">
            {t.llm.priorityLabel.replace("{priority}", String(provider.priority))}
          </Badge>
        </div>
        <p className="break-all font-mono text-xs text-muted-foreground">
          {provider.base_url}
        </p>
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>{t.llm.modelLabel}: <code className="font-mono">{provider.model}</code></span>
          {provider.api_key_masked && (
            <span>{t.llm.keyLabel}: <code className="font-mono">{provider.api_key_masked}</code></span>
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
          aria-label={provider.enabled ? t.llm.ariaToggleOff : t.llm.ariaToggleOn}
        >
          {provider.enabled ? <Power className="size-3.5" /> : <PowerOff className="size-3.5 text-muted-foreground" />}
        </Button>
        <Button size="icon" variant="ghost" className="size-8" onClick={onEdit} aria-label={t.llm.ariaEdit}>
          <Pencil className="size-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-8 text-muted-foreground hover:text-destructive"
          onClick={onDelete}
          aria-label={t.llm.ariaDelete}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

export function LLMProviderManager() {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
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
      setFormError(err instanceof Error ? err.message : t.llm.form.addFailed);
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
      setFormError(err instanceof Error ? err.message : t.llm.form.saveFailed);
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
            <h3 className="font-semibold">{t.llm.heading}</h3>
            <p className="text-xs text-muted-foreground">{t.llm.description}</p>
          </div>
          <Button
            size="sm"
            onClick={() => {
              setShowAdd(true);
              setFormError("");
            }}
          >
            <Plus className="me-1 size-4" /> {t.llm.add}
          </Button>
        </div>

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="text-sm text-destructive">{t.llm.loadFailed}</p>
        ) : providers.length === 0 ? (
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            {t.llm.empty}
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
              <DialogTitle>{t.llm.addTitle}</DialogTitle>
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
                  setFormError(t.llm.form.allFieldsRequired);
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
              <DialogTitle>{t.llm.editTitle}</DialogTitle>
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
          title={`"${confirmDelete?.name}" ${t.llm.removeButton}`}
          description={t.llm.deleteConfirmDesc}
          confirmLabel={t.llm.removeButton}
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
