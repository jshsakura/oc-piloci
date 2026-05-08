"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, FileText } from "lucide-react";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

function TranscriptViewer({ ingestId }: { ingestId: string }) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["raw-session", ingestId],
    queryFn: () => api.rawSession(ingestId),
  });

  if (isLoading) {
    return <p className="px-2 py-3 text-xs text-muted-foreground">{t.projects.transcriptLoading}</p>;
  }
  if (isError || !data) {
    return <p className="px-2 py-3 text-xs text-destructive">{t.projects.transcriptFailed}</p>;
  }
  return (
    <pre className="max-h-[420px] overflow-x-auto overflow-y-auto whitespace-pre-wrap break-all rounded-md border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">
      {data.transcript}
    </pre>
  );
}

export function ProjectSessionsPanel({ slug }: { slug: string }) {
  const { t, locale } = useTranslation();
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["project-sessions", slug],
    queryFn: () => api.projectSessions(slug),
    enabled: Boolean(slug),
  });

  const fmt = (iso: string) =>
    new Date(iso).toLocaleString(locale, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  const sessions = data?.sessions ?? [];

  if (sessions.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-muted-foreground">
          <FileText className="size-8" />
          <p className="text-sm">{t.projects.sessionsEmpty}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {sessions.map((s) => {
        const isExp = expanded === s.ingest_id;
        const status = s.error
          ? t.projects.sessionStatusFailed
          : s.processed_at
            ? t.projects.sessionStatusProcessed.replace(
                "{count}",
                String(s.memories_extracted),
              )
            : t.projects.sessionStatusPending;
        const meta = t.projects.sessionMeta
          .replace("{kb}", String(Math.round(s.size_bytes / 1024)))
          .replace("{client}", s.client);
        return (
          <Card key={s.ingest_id} className="min-w-0 overflow-hidden">
            <CardContent className="p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="break-all text-xs">
                    {s.session_id ? (
                      <span className="font-mono text-muted-foreground">
                        {s.session_id.slice(0, 12)}…
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </p>
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Badge variant="outline" className="text-[10px]">{s.client}</Badge>
                    <span>{meta}</span>
                    <span>·</span>
                    <span>{status}</span>
                    <span>·</span>
                    <span>{fmt(s.created_at)}</span>
                  </div>
                  {s.error && (
                    <p className="break-words text-[11px] text-destructive">{s.error}</p>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setExpanded(isExp ? null : s.ingest_id)}
                  className="shrink-0 gap-1 text-xs"
                >
                  {isExp ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
                  {isExp ? t.projects.hideTranscript : t.projects.viewTranscript}
                </Button>
              </div>
              {isExp && (
                <div className="mt-3">
                  <TranscriptViewer ingestId={s.ingest_id} />
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
