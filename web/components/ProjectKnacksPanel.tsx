"use client";

import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export function ProjectKnacksPanel({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ["project-knacks", slug],
    queryFn: () => api.projectKnacks(slug),
    enabled: Boolean(slug),
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  const knacks = data?.knacks ?? [];

  if (knacks.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-muted-foreground">
          <Lightbulb className="size-8" />
          <p className="text-sm">{t.projects.knacksEmpty}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {knacks.map((k) => (
        <Card key={k.instinct_id} className="min-w-0 overflow-hidden">
          <CardContent className="space-y-2 p-4">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <Badge variant="outline" className="break-all">
                {k.domain}
              </Badge>
              <span>
                {t.projects.knackCount} ×{k.instinct_count}
              </span>
              <span>·</span>
              <span>
                {t.projects.knackConfidence} {(k.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <p className="break-words text-xs text-muted-foreground">
              <span className="font-medium text-foreground">when</span> {k.trigger}
            </p>
            <p className="break-words text-sm">
              <span className="font-medium text-primary">→</span> {k.action}
            </p>
            {k.evidence_note && (
              <p className="break-words border-t pt-2 text-[11px] italic text-muted-foreground">
                {t.projects.knackEvidence}: {k.evidence_note}
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
