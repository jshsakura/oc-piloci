"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ExternalLink, FileText, UsersRound } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";

/**
 * Compact team summary embedded inside the workspace's "team" segment.
 *
 * Intentionally minimal: lets the user pick a team, see member/doc counts at
 * a glance, then jump to /teams for the full management surface. Keeps the
 * unified dashboard from inheriting the full 466-line teams page.
 */
export function TeamMiniPanel() {
  const { t } = useTranslation();
  const copy = t.dashboard.teamMini;

  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: api.listTeams });
  // Stabilize the array identity so the auto-select effect doesn't re-fire
  // every render — the spread fallback created a new [] each time otherwise.
  const teams = useMemo(() => teamsQuery.data ?? [], [teamsQuery.data]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => {
    if (!selectedId && teams.length > 0) setSelectedId(teams[0].id);
  }, [selectedId, teams]);

  const teamQuery = useQuery({
    queryKey: ["team", selectedId],
    queryFn: () => api.getTeam(selectedId as string),
    enabled: Boolean(selectedId),
  });
  const docsQuery = useQuery({
    queryKey: ["team-documents", selectedId],
    queryFn: () => api.listTeamDocuments(selectedId as string),
    enabled: Boolean(selectedId),
  });

  if (teamsQuery.isLoading) {
    return <Card><CardContent className="py-6 text-muted-foreground text-sm">···</CardContent></Card>;
  }

  if (teams.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="text-muted-foreground text-sm">{copy.empty}</p>
          <Link href="/teams">
            <Button variant="secondary" size="sm">
              <UsersRound className="me-1.5 size-4" />
              {copy.openFull}
            </Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  const team = teamQuery.data;
  const docs = docsQuery.data ?? [];
  const memberCount = team?.members?.length ?? 0;
  const docCount = docs.length;

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <UsersRound className="size-4 text-primary" aria-hidden />
          <Select value={selectedId ?? ""} onValueChange={setSelectedId}>
            <SelectTrigger className="h-8 w-44">
              <SelectValue placeholder={copy.selectPlaceholder} />
            </SelectTrigger>
            <SelectContent>
              {teams.map((tm) => (
                <SelectItem key={tm.id} value={tm.id}>
                  {tm.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardTitle>
        {selectedId && (
          <Link href={`/teams?team=${selectedId}`}>
            <Button variant="ghost" size="sm">
              <ExternalLink className="me-1.5 size-3.5" />
              {copy.openFull}
            </Button>
          </Link>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="gap-1.5">
            <UsersRound className="size-3" aria-hidden />
            {copy.members}
            <span className="text-muted-foreground ms-1 tabular-nums">{memberCount}</span>
          </Badge>
          <Badge variant="secondary" className="gap-1.5">
            <FileText className="size-3" aria-hidden />
            {copy.docs}
            <span className="text-muted-foreground ms-1 tabular-nums">{docCount}</span>
          </Badge>
        </div>
        {docs.length > 0 && (
          <ul className="divide-border divide-y rounded-md border text-sm">
            {docs.slice(0, 5).map((doc) => (
              <li key={doc.id} className="flex items-center justify-between px-3 py-2">
                <span className="truncate">{doc.path}</span>
                <span className="text-muted-foreground text-xs">v{doc.version}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
