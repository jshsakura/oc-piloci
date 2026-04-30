"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Loader2, MessageSquareText, Sparkles, StopCircle } from "lucide-react";

import AppShell from "@/components/AppShell";
import RoutePending from "@/components/RoutePending";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuthStore } from "@/lib/auth";
import { api, type ChatCitation } from "@/lib/api";
import type { Project } from "@/lib/types";

const SELECTED_KEY = "piloci-chat-selected-project";

type Turn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: ChatCitation[];
  isStreaming?: boolean;
  errorMessage?: string;
};

export default function ChatClient() {
  const router = useRouter();
  const { user, hasHydrated, isBootstrapping } = useAuthStore();

  const [projectSlug, setProjectSlug] = useState<string>("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [expandedCitations, setExpandedCitations] = useState<Record<string, boolean>>({});
  const abortRef = useRef<AbortController | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { data: projects } = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    enabled: !!user,
  });

  // Restore last-used project (or pick first available)
  useEffect(() => {
    if (!projects || projects.length === 0) return;
    if (projectSlug) return;
    let initial = "";
    if (typeof window !== "undefined") {
      const stored = window.localStorage.getItem(SELECTED_KEY) ?? "";
      if (stored && projects.some((p) => p.slug === stored)) {
        initial = stored;
      }
    }
    setProjectSlug(initial || projects[0]?.slug || "");
  }, [projects, projectSlug]);

  useEffect(() => {
    if (!projectSlug) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(SELECTED_KEY, projectSlug);
    }
  }, [projectSlug]);

  // Auth gate (mirror dashboard)
  useEffect(() => {
    if (hasHydrated && !isBootstrapping && !user) router.replace("/login");
  }, [hasHydrated, isBootstrapping, user, router]);

  // Auto-scroll on new tokens
  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns]);

  // Cancel any in-flight stream on unmount
  useEffect(() => () => abortRef.current?.abort(), []);

  const canSubmit = !!projectSlug && draft.trim().length > 0 && !busy;

  const submit = async () => {
    const query = draft.trim();
    if (!canSubmit || !projectSlug) return;
    setDraft("");
    setBusy(true);

    const userTurnId = `u-${Date.now()}`;
    const aiTurnId = `a-${Date.now()}`;
    setTurns((prev) => [
      ...prev,
      { id: userTurnId, role: "user", content: query },
      { id: aiTurnId, role: "assistant", content: "", isStreaming: true },
    ]);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    await api.chatStream(
      { query, project_slug: projectSlug },
      {
        signal: ctrl.signal,
        onCitations: (citations) => {
          setTurns((prev) =>
            prev.map((t) => (t.id === aiTurnId ? { ...t, citations } : t))
          );
        },
        onToken: (text) => {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === aiTurnId ? { ...t, content: t.content + text } : t
            )
          );
        },
        onError: (message) => {
          setTurns((prev) =>
            prev.map((t) =>
              t.id === aiTurnId
                ? { ...t, errorMessage: message, isStreaming: false }
                : t
            )
          );
        },
        onDone: () => {
          setTurns((prev) =>
            prev.map((t) => (t.id === aiTurnId ? { ...t, isStreaming: false } : t))
          );
          setBusy(false);
          abortRef.current = null;
          inputRef.current?.focus();
        },
      }
    );
  };

  const stopStream = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  };

  if (!hasHydrated || isBootstrapping) {
    return (
      <AppShell>
        <RoutePending title="세션 확인 중" description="대화를 준비하고 있습니다." />
      </AppShell>
    );
  }
  if (!user) {
    return (
      <RoutePending
        fullScreen
        title="로그인 화면으로 이동 중"
        description="인증 상태를 확인했고, 로그인 페이지로 안전하게 전환하고 있습니다."
      />
    );
  }

  const projectOptions = projects ?? [];
  const empty = turns.length === 0;

  return (
    <AppShell>
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 pb-4 pt-6">
        <header className="flex flex-col gap-1.5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <MessageSquareText className="size-5 text-muted-foreground" />
              대화로 메모리 꺼내기
            </h1>
            <p className="text-sm text-muted-foreground">
              저장된 메모리에서 답을 가져옵니다. 인용 번호로 출처를 확인하세요.
            </p>
          </div>
          <div className="flex min-w-[14rem] flex-col gap-1">
            <span className="text-xs text-muted-foreground">프로젝트</span>
            <Select value={projectSlug} onValueChange={setProjectSlug} disabled={busy}>
              <SelectTrigger>
                <SelectValue placeholder="프로젝트 선택" />
              </SelectTrigger>
              <SelectContent>
                {projectOptions.length === 0 ? (
                  <SelectItem value="__empty" disabled>
                    아직 만든 프로젝트가 없습니다
                  </SelectItem>
                ) : (
                  projectOptions.map((p) => (
                    <SelectItem key={p.slug} value={p.slug}>
                      {p.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>
        </header>

        <div
          ref={transcriptRef}
          className="flex min-h-[55vh] flex-1 flex-col gap-5 overflow-y-auto rounded-2xl border bg-card/40 p-5"
        >
          {empty ? (
            <EmptyState />
          ) : (
            turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                expandedCitations={expandedCitations}
                onToggleCitation={(refKey) =>
                  setExpandedCitations((prev) => ({ ...prev, [refKey]: !prev[refKey] }))
                }
              />
            ))
          )}
        </div>

        <ChatInput
          inputRef={inputRef}
          value={draft}
          onChange={setDraft}
          onSubmit={submit}
          onStop={stopStream}
          disabled={!projectSlug || projectOptions.length === 0}
          busy={busy}
        />
      </div>
    </AppShell>
  );
}

function EmptyState() {
  const examples = [
    "이번 주에 결정된 사항이 뭐였지?",
    "OAuth 관련해서 어떤 이슈가 있었어?",
    "내가 자주 쓰는 패턴 정리해줘",
  ];
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-10 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="size-6" />
      </div>
      <div>
        <p className="text-base font-medium">무엇을 찾고 있나요?</p>
        <p className="text-sm text-muted-foreground">
          저장된 메모리만 보고 답합니다. 검색 가능한 자연어 질문이면 충분합니다.
        </p>
      </div>
      <ul className="mt-1 flex flex-col gap-1.5 text-sm text-muted-foreground">
        {examples.map((q) => (
          <li
            key={q}
            className="rounded-full border border-dashed border-muted-foreground/20 px-3 py-1.5"
          >
            {q}
          </li>
        ))}
      </ul>
    </div>
  );
}

function TurnView({
  turn,
  expandedCitations,
  onToggleCitation,
}: {
  turn: Turn;
  expandedCitations: Record<string, boolean>;
  onToggleCitation: (refKey: string) => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground shadow-sm">
          {turn.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm leading-relaxed text-foreground">
        {turn.content || (turn.isStreaming ? <ThinkingDots /> : null)}
        {turn.isStreaming && turn.content && (
          <span className="ml-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-foreground/60 align-middle" />
        )}
      </div>
      {turn.errorMessage && (
        <p className="text-sm text-destructive">오류: {turn.errorMessage}</p>
      )}
      {turn.citations && turn.citations.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap gap-1.5">
            {turn.citations.map((c) => {
              const key = `${turn.id}:${c.ref}`;
              const expanded = !!expandedCitations[key];
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => onToggleCitation(key)}
                  className="group inline-flex items-center gap-1.5 rounded-full border bg-muted/40 px-2.5 py-0.5 text-xs text-muted-foreground transition hover:bg-muted"
                  aria-expanded={expanded}
                >
                  <span className="font-mono text-[10px] text-foreground/80">[{c.ref}]</span>
                  <span className="max-w-[18ch] truncate">{c.content}</span>
                  {typeof c.score === "number" && (
                    <span className="text-[10px] text-muted-foreground/70">
                      {(c.score * 100).toFixed(0)}%
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {turn.citations.map((c) => {
            const key = `${turn.id}:${c.ref}`;
            if (!expandedCitations[key]) return null;
            return (
              <div
                key={`${key}:exp`}
                className="rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-mono text-[10px] text-foreground/70">[{c.ref}]</span>
                  {c.tags.length > 0 && (
                    <span className="text-[10px]">tags: {c.tags.join(", ")}</span>
                  )}
                </div>
                <p className="whitespace-pre-wrap leading-relaxed text-foreground/90">
                  {c.content}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      메모리에서 단서를 찾는 중…
    </span>
  );
}

function ChatInput({
  inputRef,
  value,
  onChange,
  onSubmit,
  onStop,
  disabled,
  busy,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  disabled: boolean;
  busy: boolean;
}) {
  const placeholder = useMemo(
    () =>
      disabled
        ? "프로젝트를 먼저 선택해주세요"
        : "예: 지난 회의에서 누가 무슨 결정을 했지?",
    [disabled]
  );

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="sticky bottom-2 flex items-end gap-2 rounded-2xl border bg-background p-2 shadow-lg"
    >
      <textarea
        ref={inputRef}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSubmit();
          }
        }}
        rows={1}
        placeholder={placeholder}
        className="flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/70 disabled:opacity-50"
        aria-label="질문 입력"
      />
      {busy ? (
        <Button type="button" size="icon" variant="outline" onClick={onStop} aria-label="중지">
          <StopCircle className="size-4" />
        </Button>
      ) : (
        <Button
          type="submit"
          size="icon"
          disabled={disabled || value.trim().length === 0}
          aria-label="보내기"
        >
          <ArrowUp className="size-4" />
        </Button>
      )}
    </form>
  );
}
