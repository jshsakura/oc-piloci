"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Loader2, MessageSquareText, Mic, MicOff, Sparkles, StopCircle } from "lucide-react";

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
import { useTranslation } from "@/lib/i18n";
import type { Project } from "@/lib/types";

type ChatCopy = ReturnType<typeof useTranslation>["t"]["chat"];

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
  const { t } = useTranslation();

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
        <RoutePending title={t.chat.pendingTitle} description={t.chat.pendingDesc} />
      </AppShell>
    );
  }
  if (!user) {
    return (
      <RoutePending
        fullScreen
        title={t.chat.redirectTitle}
        description={t.chat.redirectDesc}
      />
    );
  }

  const projectOptions = projects ?? [];
  const empty = turns.length === 0;

  return (
    <AppShell>
      <div className="flex w-full flex-col gap-4 pb-4">
        <header className="pi-page-hero flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="pi-eyebrow">{t.chat.eyebrow}</p>
            <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-[-0.03em]">
              <MessageSquareText className="size-5 text-primary" />
              {t.chat.title}
            </h1>
            <p className="pi-subtitle">
              {t.chat.subtitle}
            </p>
          </div>
          <Select value={projectSlug} onValueChange={setProjectSlug} disabled={busy}>
            <SelectTrigger
              className="pi-soft-input h-9 w-auto min-w-36 gap-1.5 px-3 text-xs font-medium text-muted-foreground hover:text-foreground"
              aria-label={t.chat.projectSelectAria}
            >
              <SelectValue placeholder={t.chat.projectPlaceholder} />
            </SelectTrigger>
            <SelectContent align="end">
              {projectOptions.length === 0 ? (
                <SelectItem value="__empty" disabled>
                  {t.chat.noProjects}
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
        </header>

        <div
          ref={transcriptRef}
          className="pi-panel flex min-h-[55vh] flex-1 flex-col gap-5 overflow-y-auto p-5"
        >
          {empty ? (
            <EmptyState chatCopy={t.chat} />
          ) : (
            turns.map((turn) => (
              <TurnView
                key={turn.id}
                turn={turn}
                expandedCitations={expandedCitations}
                onToggleCitation={(refKey) =>
                  setExpandedCitations((prev) => ({ ...prev, [refKey]: !prev[refKey] }))
                }
                errorPrefix={t.chat.errorPrefix}
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
          chatCopy={t.chat}
        />
      </div>
    </AppShell>
  );
}

function EmptyState({ chatCopy }: { chatCopy: ChatCopy }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-10 text-center">
      <div className="pi-icon-cell size-12 rounded-full">
        <Sparkles className="size-6" />
      </div>
      <div>
        <p className="text-base font-medium">{chatCopy.emptyTitle}</p>
        <p className="text-sm text-muted-foreground">
          {chatCopy.emptyDesc}
        </p>
      </div>
      <ul className="mt-1 flex flex-col gap-1.5 text-sm text-muted-foreground">
        {chatCopy.examples.map((q) => (
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
  errorPrefix,
}: {
  turn: Turn;
  expandedCitations: Record<string, boolean>;
  onToggleCitation: (refKey: string) => void;
  errorPrefix: string;
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
          <span className="ms-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-foreground/60 align-middle" />
        )}
      </div>
      {turn.errorMessage && (
        <p className="text-sm text-destructive">{errorPrefix}: {turn.errorMessage}</p>
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
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" />
      {t.chat.thinking}
    </span>
  );
}

// Minimal Web Speech API surface — typed locally to avoid `any` while keeping
// the implementation self-contained. Browsers expose this as either
// ``SpeechRecognition`` (Firefox spec name) or ``webkitSpeechRecognition``.
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

// Map SpeechRecognition error codes to a human-readable hint. Surfaced in the
// UI so users can self-diagnose (mic permission, HTTP origin, etc.) instead of
// silently watching the button bounce back.
function describeDictationError(code: string, dict: ChatCopy["dictation"]): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return dict.notAllowed;
    case "audio-capture":
      return dict.audioCapture;
    case "network":
      return dict.network;
    case "no-speech":
      return dict.noSpeech;
    case "aborted":
      return dict.aborted;
    case "insecure-context":
      return dict.insecureContext;
    default:
      return `${dict.unknown} (${code}). ${dict.consoleHint}`;
  }
}

function useDictation({
  onAppend,
  enabled,
  dict,
}: {
  onAppend: (text: string) => void;
  enabled: boolean;
  dict: ChatCopy["dictation"];
}) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const [secureContext, setSecureContext] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // Track whether THIS recognition session produced any final result before
  // onend fires. Safari sometimes ends without ``onerror`` (e.g. denied mic)
  // and we want to distinguish that from a clean no-input session.
  const gotResultRef = useRef(false);
  // Keep the latest onAppend in a ref so the recognition handler doesn't
  // capture a stale closure when the parent's draft state updates.
  const onAppendRef = useRef(onAppend);
  onAppendRef.current = onAppend;

  useEffect(() => {
    setSupported(getSpeechRecognition() !== null);
    setSecureContext(typeof window === "undefined" ? true : window.isSecureContext);
  }, []);

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop();
      } catch {
        // ignore — cleanup only
      }
    };
  }, []);

  const start = () => {
    if (!enabled || listening) return;
    if (!secureContext) {
      setError(describeDictationError("insecure-context", dict));
      return;
    }
    const Ctor = getSpeechRecognition();
    if (!Ctor) return;

    let rec: SpeechRecognitionLike;
    try {
      rec = new Ctor();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[piloci] SpeechRecognition ctor failed", e);
      setError(dict.startFailed);
      return;
    }

    // Match what Safari/webkit handles best: a single utterance with interim
    // results enabled. ``interimResults: false`` has been observed to make
    // Safari end the session immediately with no result and no error.
    rec.lang = "ko-KR";
    rec.continuous = false;
    rec.interimResults = true;

    gotResultRef.current = false;
    setError(null);

    rec.onresult = (event) => {
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
      }
      if (finalText) {
        gotResultRef.current = true;
        onAppendRef.current(finalText);
      }
    };
    rec.onend = () => {
      setListening(false);
      recognitionRef.current = null;
      // If the session ended without ever producing a final result and no
      // explicit error fired, hint that something silently failed.
      if (!gotResultRef.current) {
        setError((prev) => prev ?? dict.silentFailure);
      }
    };
    rec.onerror = (event) => {
      // eslint-disable-next-line no-console
      console.error("[piloci] SpeechRecognition error", event.error);
      setError(describeDictationError(event.error, dict));
      setListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = rec;
    setListening(true);
    try {
      rec.start();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error("[piloci] SpeechRecognition start() threw", e);
      setError(dict.startRetry);
      setListening(false);
      recognitionRef.current = null;
    }
  };

  const stop = () => {
    try {
      recognitionRef.current?.stop();
    } catch {
      // ignore
    }
  };

  const dismissError = () => setError(null);

  return { listening, supported, secureContext, error, start, stop, dismissError };
}

function ChatInput({
  inputRef,
  value,
  onChange,
  onSubmit,
  onStop,
  disabled,
  busy,
  chatCopy,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  disabled: boolean;
  busy: boolean;
  chatCopy: ChatCopy;
}) {
  const placeholder = useMemo(
    () =>
      disabled
        ? chatCopy.placeholderDisabled
        : chatCopy.placeholderActive,
    [disabled, chatCopy.placeholderDisabled, chatCopy.placeholderActive]
  );

  const dictation = useDictation({
    enabled: !disabled && !busy,
    onAppend: (text) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const next = value.trim().length === 0 ? trimmed : `${value} ${trimmed}`;
      onChange(next);
      // Defer focus so the textarea is ready after state propagates.
      requestAnimationFrame(() => inputRef.current?.focus());
    },
    dict: chatCopy.dictation,
  });

  const toggleMic = () => {
    if (dictation.listening) dictation.stop();
    else dictation.start();
  };

  return (
    <div className="sticky bottom-2 flex flex-col gap-1.5">
      {dictation.error && (
        <div
          className="flex items-start justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-sm dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
          role="alert"
        >
          <span className="leading-relaxed">{dictation.error}</span>
          <button
            type="button"
            onClick={dictation.dismissError}
            className="shrink-0 text-amber-700 hover:text-amber-900 dark:text-amber-300 dark:hover:text-amber-100"
            aria-label={chatCopy.input.closeErrorAria}
          >
            ×
          </button>
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        className="pi-panel flex items-end gap-2 p-2"
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
        className="min-w-0 flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:truncate placeholder:text-muted-foreground/70 disabled:opacity-50"
        aria-label={chatCopy.input.questionAria}
      />
      {dictation.supported && (
        <Button
          type="button"
          size="icon"
          variant={dictation.listening ? "destructive" : "outline"}
          onClick={toggleMic}
          disabled={disabled || busy}
          aria-label={dictation.listening ? chatCopy.input.micStopAria : chatCopy.input.micStartAria}
          aria-pressed={dictation.listening}
          title={dictation.listening ? chatCopy.input.micRecordingTitle : chatCopy.input.micIdleTitle}
          className={dictation.listening ? "animate-pulse" : undefined}
        >
          {dictation.listening ? <MicOff className="size-4" /> : <Mic className="size-4" />}
        </Button>
      )}
      {busy ? (
        <Button type="button" size="icon" variant="outline" onClick={onStop} aria-label={chatCopy.input.stopAria}>
          <StopCircle className="size-4" />
        </Button>
      ) : (
        <Button
          type="submit"
          size="icon"
          disabled={disabled || value.trim().length === 0}
          aria-label={chatCopy.input.sendAria}
        >
          <ArrowUp className="size-4" />
        </Button>
      )}
      </form>
    </div>
  );
}
