"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Inbox, MailPlus, RefreshCcw, Trash2, UsersRound } from "lucide-react";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { TeamDocumentPull, TeamDocumentSummary, TeamSummary } from "@/lib/types";

type Notice = { tone: "ok" | "error"; text: string } | null;
const EMPTY_TEAMS: TeamSummary[] = [];

export default function TeamsPage() {
  const queryClient = useQueryClient();
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [teamName, setTeamName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [docPath, setDocPath] = useState("notes.md");
  const [docContent, setDocContent] = useState("");
  const [editingDoc, setEditingDoc] = useState<TeamDocumentSummary | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: api.listTeams });
  const pendingInvitesQuery = useQuery({
    queryKey: ["team-pending-invites"],
    queryFn: api.listPendingInvites,
  });

  const teams = teamsQuery.data ?? EMPTY_TEAMS;

  useEffect(() => {
    if (!selectedTeamId && teams.length > 0) setSelectedTeamId(teams[0].id);
  }, [selectedTeamId, teams]);

  const teamQuery = useQuery({
    queryKey: ["team", selectedTeamId],
    queryFn: () => api.getTeam(selectedTeamId as string),
    enabled: Boolean(selectedTeamId),
  });
  const invitesQuery = useQuery({
    queryKey: ["team-invites", selectedTeamId],
    queryFn: () => api.listTeamInvites(selectedTeamId as string),
    enabled: Boolean(selectedTeamId),
  });
  const docsQuery = useQuery({
    queryKey: ["team-documents", selectedTeamId],
    queryFn: () => api.listTeamDocuments(selectedTeamId as string),
    enabled: Boolean(selectedTeamId),
  });

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) ?? null,
    [selectedTeamId, teams],
  );

  const createTeamMutation = useMutation({
    mutationFn: () => api.createTeam(teamName.trim()),
    onSuccess: (team: TeamSummary) => {
      setTeamName("");
      setSelectedTeamId(team.id);
      setNotice({ tone: "ok", text: "팀을 만들었습니다." });
      queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
    onError: (error: unknown) => setNotice(toError(error, "팀 생성에 실패했습니다.")),
  });

  const inviteMutation = useMutation({
    mutationFn: () => api.createTeamInvite(selectedTeamId as string, inviteEmail.trim()),
    onSuccess: () => {
      setInviteEmail("");
      setNotice({ tone: "ok", text: "초대를 만들었습니다. 상대의 대기 초대함에도 표시됩니다." });
      queryClient.invalidateQueries({ queryKey: ["team-invites", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, "초대에 실패했습니다.")),
  });

  const respondInviteMutation = useMutation({
    mutationFn: ({ inviteId, action }: { inviteId: string; action: "accept" | "reject" }) =>
      api.respondInvite(inviteId, action),
    onSuccess: () => {
      setNotice({ tone: "ok", text: "초대 상태를 반영했습니다." });
      queryClient.invalidateQueries({ queryKey: ["team-pending-invites"] });
      queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
    onError: (error: unknown) => setNotice(toError(error, "초대 응답에 실패했습니다.")),
  });

  const createDocMutation = useMutation({
    mutationFn: () =>
      api.createTeamDocument(selectedTeamId as string, {
        path: docPath.trim(),
        content: docContent,
      }),
    onSuccess: () => {
      setDocPath("notes.md");
      setDocContent("");
      setNotice({ tone: "ok", text: "팀 문서를 저장했습니다." });
      queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, "문서 저장에 실패했습니다.")),
  });

  const updateDocMutation = useMutation({
    mutationFn: () =>
      api.updateTeamDocument(selectedTeamId as string, editingDoc?.id ?? "", {
        content: docContent,
        parent_hash: editingDoc?.content_hash,
      }),
    onSuccess: () => {
      setEditingDoc(null);
      setDocPath("notes.md");
      setDocContent("");
      setNotice({ tone: "ok", text: "팀 문서를 갱신했습니다." });
      queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, "문서 갱신에 실패했습니다.")),
  });

  const deleteDocMutation = useMutation({
    mutationFn: (docId: string) => api.deleteTeamDocument(selectedTeamId as string, docId),
    onSuccess: () => {
      setNotice({ tone: "ok", text: "팀 문서를 삭제했습니다." });
      queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, "문서 삭제에 실패했습니다.")),
  });

  const docs = docsQuery.data ?? [];
  const manifest = Object.fromEntries(docs.map((doc) => [doc.path, doc.content_hash]));
  const pullQuery = useQuery<TeamDocumentPull>({
    queryKey: ["team-documents-pull", selectedTeamId, docs.length],
    queryFn: () => api.pullTeamDocuments(selectedTeamId as string, manifest),
    enabled: Boolean(selectedTeamId) && docs.length > 0,
  });

  const selectDocument = (doc: TeamDocumentSummary) => {
    const pulled = [...(pullQuery.data?.added ?? []), ...(pullQuery.data?.modified ?? [])].find(
      (item) => item.id === doc.id,
    );
    setEditingDoc(doc);
    setDocPath(doc.path);
    setDocContent(pulled?.content ?? "");
    setNotice(
      pulled
        ? null
        : { tone: "ok", text: "목록 메타데이터만 불러왔습니다. 내용은 다음 동기화 차이에 포함될 때 표시됩니다." },
    );
  };

  return (
    <AppShell title="팀 작업공간">
      {/* v0.3.58: create-team form moved out of header actions into a
          slim row inline at the top of the page body. */}
      <div className="mb-3 flex items-center justify-end">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!teamName.trim()) return setNotice({ tone: "error", text: "팀 이름을 입력하세요." });
            createTeamMutation.mutate();
          }}
        >
          <Input
            value={teamName}
            onChange={(event) => setTeamName(event.target.value)}
            placeholder="새 팀 이름"
            aria-label="새 팀 이름"
            className="h-8 w-40 text-sm"
          />
          <Button type="submit" size="sm" disabled={createTeamMutation.isPending}>
            만들기
          </Button>
        </form>
      </div>
      {notice && (
        <div
          className={`mt-4 rounded-xl border px-4 py-3 text-sm ${
            notice.tone === "error" ? "border-destructive/30 text-destructive" : "text-muted-foreground"
          }`}
        >
          {notice.text}
        </div>
      )}

      {/* items-start: side stack and main pane line up at the top instead
          of stretching to match each other (v0.3.58 — the user noticed
          uneven internal heights). */}
      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <UsersRound className="size-4" /> 내 팀
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {teamsQuery.isLoading ? (
                [1, 2, 3].map((item) => <Skeleton key={item} className="h-12 rounded-xl" />)
              ) : teams.length === 0 ? (
                <EmptyState icon={UsersRound} text="아직 팀이 없습니다." />
              ) : (
                teams.map((team) => (
                  <button
                    key={team.id}
                    type="button"
                    onClick={() => setSelectedTeamId(team.id)}
                    className={`w-full rounded-xl border px-3 py-2 text-left transition-colors hover:bg-accent ${
                      team.id === selectedTeamId ? "border-primary bg-primary/5" : "bg-background"
                    }`}
                  >
                    <p className="truncate text-sm font-medium">{team.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(team.created_at).toLocaleDateString("ko-KR")}
                    </p>
                  </button>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Inbox className="size-4" /> 받은 초대
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(pendingInvitesQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">대기 중인 초대가 없습니다.</p>
              ) : (
                pendingInvitesQuery.data?.map((invite) => (
                  <div key={invite.id} className="rounded-xl border p-3">
                    <p className="text-sm font-medium">{invite.team_name}</p>
                    <p className="text-xs text-muted-foreground">
                      만료 {new Date(invite.expires_at).toLocaleDateString("ko-KR")}
                    </p>
                    <div className="mt-3 flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => respondInviteMutation.mutate({ inviteId: invite.id, action: "accept" })}
                      >
                        수락
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => respondInviteMutation.mutate({ inviteId: invite.id, action: "reject" })}
                      >
                        거절
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </aside>

        <section className="space-y-4">
          {!selectedTeam ? (
            // No-team skeleton: previews the same right-pane shape the user
            // gets once a team is selected (overview / docs / new-doc form),
            // with the hint centered as a call-to-action.
            <div className="relative space-y-4">
              <Card>
                <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-2">
                    <div className="bg-muted/40 h-5 w-32 animate-pulse rounded" />
                    <div className="bg-muted/30 h-3 w-20 animate-pulse rounded" />
                  </div>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <div className="bg-muted/40 h-3 w-10 animate-pulse rounded" />
                    <div className="bg-muted/20 h-14 animate-pulse rounded-xl" />
                    <div className="bg-muted/20 h-14 animate-pulse rounded-xl" />
                  </div>
                  <div className="space-y-3 rounded-xl border p-3">
                    <div className="bg-muted/40 h-3 w-24 animate-pulse rounded" />
                    <div className="bg-muted/30 h-9 animate-pulse rounded" />
                  </div>
                </CardContent>
              </Card>

              <div className="grid gap-4 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
                <Card>
                  <CardHeader>
                    <div className="bg-muted/40 h-4 w-20 animate-pulse rounded" />
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <div key={i} className="bg-muted/20 h-14 animate-pulse rounded-xl" />
                    ))}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <div className="bg-muted/40 h-4 w-24 animate-pulse rounded" />
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="bg-muted/30 h-9 animate-pulse rounded" />
                    <div className="bg-muted/20 h-40 animate-pulse rounded" />
                  </CardContent>
                </Card>
              </div>

              {/* Hint overlay */}
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4">
                <div className="bg-background/95 text-muted-foreground rounded-lg border px-5 py-3 text-center text-sm shadow-md backdrop-blur-sm">
                  먼저 팀을 만들거나 선택해주세요.
                </div>
              </div>
            </div>
          ) : (
            <>
              <Card>
                <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <CardTitle>{teamQuery.data?.name ?? selectedTeam.name}</CardTitle>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {teamQuery.data?.members.length ?? 0}명 참여 중
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      teamsQuery.refetch();
                      teamQuery.refetch();
                      docsQuery.refetch();
                      invitesQuery.refetch();
                    }}
                  >
                    <RefreshCcw className="me-2 size-4" /> 새로고침
                  </Button>
                </CardHeader>
                <CardContent className="grid gap-4 md:grid-cols-2 md:items-stretch">
                  <div className="flex flex-col gap-2">
                    <Label>멤버</Label>
                    <div className="flex h-full flex-col gap-2 rounded-xl border p-3">
                      {teamQuery.data?.members.map((member) => (
                        <div
                          key={member.user_id}
                          className="flex items-center justify-between gap-3 rounded-lg bg-muted/30 px-3 py-2"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">{member.email}</p>
                            <p className="truncate text-xs text-muted-foreground">{member.user_id}</p>
                          </div>
                          <Badge variant={member.role === "owner" ? "default" : "secondary"}>
                            {member.role}
                          </Badge>
                        </div>
                      )) ?? <Skeleton className="h-12 rounded-lg" />}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2">
                    <Label htmlFor="team-invite">이메일로 초대</Label>
                    <form
                      className="flex h-full flex-col gap-3 rounded-xl border p-3"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!inviteEmail.trim())
                          return setNotice({ tone: "error", text: "초대할 이메일을 입력하세요." });
                        inviteMutation.mutate();
                      }}
                    >
                      <div className="flex gap-2">
                        <Input
                          id="team-invite"
                          type="email"
                          value={inviteEmail}
                          onChange={(event) => setInviteEmail(event.target.value)}
                          placeholder="teammate@example.com"
                        />
                        <Button type="submit" disabled={inviteMutation.isPending}>
                          <MailPlus className="size-4" />
                        </Button>
                      </div>

                      {(invitesQuery.data ?? []).length > 0 ? (
                        <div className="flex flex-1 flex-col gap-1.5 overflow-hidden">
                          <p className="text-xs font-medium text-muted-foreground">보낸 초대</p>
                          <div className="flex flex-col gap-1.5">
                            {(invitesQuery.data ?? []).slice(0, 4).map((invite) => (
                              <div
                                key={invite.id}
                                className="flex items-center justify-between gap-2 rounded-lg bg-muted/30 px-3 py-1.5 text-xs"
                              >
                                <span className="truncate text-muted-foreground">{invite.invitee_email}</span>
                                <Badge variant="outline" className="shrink-0">
                                  {invite.status}
                                </Badge>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <p className="flex flex-1 items-center text-xs text-muted-foreground">
                          아직 보낸 초대가 없습니다.
                        </p>
                      )}
                    </form>
                  </div>
                </CardContent>
              </Card>

              <div className="grid gap-4 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <FileText className="size-4" /> 팀 문서
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {docsQuery.isLoading ? (
                      [1, 2, 3].map((item) => <Skeleton key={item} className="h-14 rounded-xl" />)
                    ) : docs.length === 0 ? (
                      <EmptyState icon={FileText} text="아직 공유 문서가 없습니다." />
                    ) : (
                      docs.map((doc) => (
                        <button
                          key={doc.id}
                          type="button"
                          onClick={() => selectDocument(doc)}
                          className={`w-full rounded-xl border p-3 text-left hover:bg-accent ${
                            editingDoc?.id === doc.id ? "border-primary bg-primary/5" : "bg-background"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="break-all text-sm font-medium">{doc.path}</p>
                              <p className="text-xs text-muted-foreground">v{doc.version}</p>
                            </div>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={(event) => {
                                event.stopPropagation();
                                deleteDocMutation.mutate(doc.id);
                              }}
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          </div>
                        </button>
                      ))
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">{editingDoc ? "문서 수정" : "새 문서 작성"}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <form
                      className="space-y-4"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!docPath.trim()) return setNotice({ tone: "error", text: "문서 경로를 입력하세요." });
                        if (editingDoc) updateDocMutation.mutate();
                        else createDocMutation.mutate();
                      }}
                    >
                      <div className="space-y-2">
                        <Label htmlFor="team-doc-path">경로</Label>
                        <Input
                          id="team-doc-path"
                          value={docPath}
                          disabled={Boolean(editingDoc)}
                          onChange={(event) => setDocPath(event.target.value)}
                          placeholder="notes.md"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="team-doc-content">내용</Label>
                        <textarea
                          id="team-doc-content"
                          value={docContent}
                          onChange={(event) => setDocContent(event.target.value)}
                          placeholder="팀이 함께 볼 내용을 적어두세요."
                          className="min-h-64 w-full rounded-xl border bg-background px-3 py-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>
                      <div className="flex flex-wrap justify-end gap-2">
                        {editingDoc && (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => {
                              setEditingDoc(null);
                              setDocPath("notes.md");
                              setDocContent("");
                            }}
                          >
                            새 문서로 전환
                          </Button>
                        )}
                        <Button type="submit" disabled={createDocMutation.isPending || updateDocMutation.isPending}>
                          {editingDoc ? "갱신" : "저장"}
                        </Button>
                      </div>
                    </form>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}

function EmptyState({ icon: Icon, text }: { icon: typeof UsersRound; text: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center text-muted-foreground">
      <Icon className="size-8" />
      <p className="text-sm">{text}</p>
    </div>
  );
}

function toError(error: unknown, fallback: string): Notice {
  return { tone: "error", text: error instanceof Error ? error.message : fallback };
}
