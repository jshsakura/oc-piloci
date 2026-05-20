"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Check,
  Copy,
  Download,
  ExternalLink,
  File as FileIcon,
  FileArchive,
  FileText,
  Inbox,
  MailPlus,
  Map as MapIcon,
  RefreshCcw,
  Trash2,
  Upload,
  UsersRound,
  X,
} from "lucide-react";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { WikiMiniMap } from "@/components/WikiMiniMap";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import type {
  GraphNode,
  TeamDocumentSummary,
  TeamSummary,
} from "@/lib/types";

function humanizeSize(bytes?: number): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileExt(path: string): string {
  const dot = path.lastIndexOf(".");
  return dot >= 0 ? path.slice(dot + 1).toLowerCase() : "";
}

type FileTypesCopy = { markdown: string; text: string; image: string; binary: string };

// Extension → display label. Brand/format names (Python, JS, JSON, …) are kept
// as-is; the four localizable buckets resolve from copy at call time.
function typeLabelMap(ft: FileTypesCopy): Record<string, string> {
  return {
    md: ft.markdown, txt: ft.text, py: "Python", js: "JS", ts: "TS", tsx: "TSX",
    jsx: "JSX", json: "JSON", yaml: "YAML", yml: "YAML", toml: "TOML", csv: "CSV",
    html: "HTML", css: "CSS", sql: "SQL", sh: "Shell", rst: "reST", pdf: "PDF",
    png: ft.image, jpg: ft.image, jpeg: ft.image, gif: ft.image, webp: ft.image, svg: ft.image,
    xlsx: "Excel", xls: "Excel", docx: "Word", doc: "Word", pptx: "PowerPoint", zip: "ZIP",
  };
}

// Friendly type chip. Extension wins (a .md uploaded as text has no mime, so
// "text" used to leak through); fall back to mime, then a coarse default.
function fileTypeLabel(
  ft: FileTypesCopy,
  path: string,
  mime?: string | null,
  isBinary?: boolean,
): string {
  const label = typeLabelMap(ft)[fileExt(path)];
  if (label) return label;
  if (mime) return mime;
  return isBinary ? ft.binary : ft.text;
}

// Browser can render these inline in a new tab; everything else just downloads.
// (xlsx/docx aren't browser-renderable without a public Office viewer, which a
// self-hosted instance can't use — so they fall through to download.)
const _VIEWABLE_EXT = new Set([
  "md", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml", "toml",
  "csv", "html", "css", "sql", "sh", "rst", "ini", "cfg", "log", "pdf",
  "png", "jpg", "jpeg", "gif", "webp", "svg",
]);

function isViewable(path: string, mime?: string | null): boolean {
  if (_VIEWABLE_EXT.has(fileExt(path))) return true;
  if (mime && (mime.startsWith("text/") || mime === "application/pdf" || mime.startsWith("image/")))
    return true;
  return false;
}

const _IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg"]);

function isImage(path: string, mime?: string | null): boolean {
  if (_IMAGE_EXT.has(fileExt(path))) return true;
  return Boolean(mime && mime.startsWith("image/"));
}

function isPdf(path: string, mime?: string | null): boolean {
  return fileExt(path) === "pdf" || mime === "application/pdf";
}

// A node's file is browser-viewable when its path extension renders inline;
// otherwise the popup offers a download instead of an "open".
function nodeViewable(node: GraphNode): boolean {
  const path = node.path ?? node.label ?? "";
  return _VIEWABLE_EXT.has(fileExt(path));
}

function localPart(email: string): string {
  const at = email.indexOf("@");
  return at > 0 ? email.slice(0, at) : email;
}

// Compact attribution chip: shows just the label + email local-part on one
// line, and reveals the full email with a copy button on hover.
function EmailChip({ label, email }: { label: string; email: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(email);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — title attr still exposes the full email */
    }
  };
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex min-w-0 max-w-full items-center gap-1" title={email}>
            <span className="text-muted-foreground/80">{label}</span>
            <span className="truncate font-medium text-foreground/80">{localPart(email)}</span>
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="flex items-center gap-2 border bg-popover text-popover-foreground"
        >
          <span className="font-mono text-[11px]">{email}</span>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              copy();
            }}
            className="rounded p-0.5 hover:bg-accent"
            aria-label={t.teams.page.copyEmail}
          >
            {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          </button>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
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

// In-app preview for team documents. Text/markdown/code render inline (fetched
// via getTeamDocument); images and PDFs load through the /raw?inline=1 URL so
// the browser displays rather than downloads them. Non-viewable formats show a
// short "no preview" note. Every type keeps a download affordance in the footer.
function DocPreviewDialog({
  teamId,
  doc,
  onClose,
}: {
  teamId: string;
  doc: TeamDocumentSummary | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const copy = t.teams.docs.preview;
  const open = Boolean(doc);
  const path = doc?.path ?? "";
  const mime = doc?.mime;
  const viewable = doc ? isViewable(path, mime) : false;
  const image = doc ? isImage(path, mime) : false;
  const pdf = doc ? isPdf(path, mime) : false;
  // Text/markdown/code: anything viewable that isn't an image or pdf.
  const textual = viewable && !image && !pdf;

  const rawUrl = doc ? api.teamDocumentRawUrl(teamId, doc.id) : "";
  const inlineUrl = rawUrl ? `${rawUrl}?inline=1` : "";

  const contentQuery = useQuery({
    queryKey: ["team-document-preview", teamId, doc?.id],
    queryFn: () => api.getTeamDocument(teamId, doc!.id),
    enabled: open && textual,
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="break-all">{copy.title}: {path}</DialogTitle>
        </DialogHeader>
        <div className="max-h-[70vh] overflow-auto">
          {!viewable ? (
            <p className="py-8 text-center text-sm text-muted-foreground">{copy.unsupported}</p>
          ) : image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={inlineUrl}
              alt={path}
              className="mx-auto max-h-[70vh] w-auto object-contain"
            />
          ) : pdf ? (
            <iframe src={inlineUrl} title={path} className="h-[70vh] w-full rounded-md border" />
          ) : contentQuery.isLoading ? (
            <div className="space-y-3 py-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-4/5" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : contentQuery.isError ? (
            <p className="py-8 text-center text-sm text-destructive">
              {contentQuery.error instanceof Error
                ? contentQuery.error.message
                : copy.unsupported}
            </p>
          ) : (
            <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 font-mono text-xs leading-relaxed">
              {contentQuery.data?.content ?? ""}
            </pre>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {copy.close}
          </Button>
          {doc && (
            <Button asChild>
              <a href={rawUrl} target="_blank" rel="noreferrer">
                <Download className="me-2 size-4" /> {copy.download}
              </a>
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type Notice = { tone: "ok" | "error"; text: string } | null;
function toError(error: unknown, fallback: string): Notice {
  return { tone: "error", text: error instanceof Error ? error.message : fallback };
}

const EMPTY_TEAMS: TeamSummary[] = [];
type TabKey = "settings" | "map";
const TAB_KEYS: TabKey[] = ["settings", "map"];

function TeamsSuspenseFallback() {
  const { t } = useTranslation();
  return (
    <AppShell title={t.teams.page.title}>
      <p className="text-sm text-muted-foreground">{t.teams.wiki.loading}</p>
    </AppShell>
  );
}

export default function TeamsPage() {
  // useSearchParams() requires a Suspense boundary under static export.
  return (
    <Suspense fallback={<TeamsSuspenseFallback />}>
      <TeamsShell />
    </Suspense>
  );
}

function TeamsShell() {
  const { t } = useTranslation();
  const copy = t.teams;
  const router = useRouter();
  const searchParams = useSearchParams();

  const teamsQuery = useQuery({ queryKey: ["teams"], queryFn: api.listTeams });
  const teams = teamsQuery.data ?? EMPTY_TEAMS;

  // Team + active tab live in the URL so the page is static-export safe (no
  // [id] dynamic segment) and shareable/back-button friendly.
  const urlTeamId = searchParams?.get("id") ?? "";
  const urlTab = (searchParams?.get("tab") ?? "settings") as TabKey;
  const activeTab: TabKey = TAB_KEYS.includes(urlTab) ? urlTab : "settings";
  const selectedTeamId = urlTeamId || (teams.length > 0 ? teams[0].id : "");

  // Default the URL to the first team once teams load and none was selected,
  // mirroring the old auto-select behaviour.
  useEffect(() => {
    if (!urlTeamId && teams.length > 0) {
      const next = new URLSearchParams(searchParams?.toString());
      next.set("id", teams[0].id);
      router.replace(`/teams?${next.toString()}`);
    }
  }, [urlTeamId, teams, router, searchParams]);

  const setTeam = (id: string) => {
    const next = new URLSearchParams(searchParams?.toString());
    next.set("id", id);
    router.push(`/teams?${next.toString()}`);
  };

  const setTab = (tab: string) => {
    const next = new URLSearchParams(searchParams?.toString());
    next.set("tab", tab);
    router.push(`/teams?${next.toString()}`);
  };

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) ?? null,
    [selectedTeamId, teams],
  );

  return (
    <AppShell title={copy.page.title}>
      <div className="mb-4 flex flex-col gap-3">
        {/* Team selector: a plain select keeps static export trivial and
            matches the old wiki dropdown. */}
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-sm font-medium text-muted-foreground" htmlFor="team-select">
            {copy.tabs.teamSelect}
          </label>
          <select
            id="team-select"
            className="h-9 min-w-48 rounded-lg border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={selectedTeamId}
            onChange={(event) => setTeam(event.target.value)}
            disabled={teams.length === 0}
          >
            <option value="" disabled>
              {copy.tabs.teamSelectPlaceholder}
            </option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </div>

        <Tabs value={activeTab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="settings">{copy.tabs.settings}</TabsTrigger>
            <TabsTrigger value="map">{copy.tabs.map}</TabsTrigger>
          </TabsList>

          <TabsContent value="settings" className="mt-4">
            <SettingsTab
              teams={teams}
              teamsQuery={teamsQuery}
              selectedTeam={selectedTeam}
              selectedTeamId={selectedTeamId}
              onSelectTeam={setTeam}
            />
          </TabsContent>
          <TabsContent value="map" className="mt-4">
            {selectedTeamId ? (
              <MapTab teamId={selectedTeamId} />
            ) : (
              <NoTeamHint text={copy.tabs.noTeam} />
            )}
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}

function NoTeamHint({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
      {text}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 설정 tab: team management — members, invites, files.
// ---------------------------------------------------------------------------

interface SettingsTabProps {
  teams: TeamSummary[];
  teamsQuery: ReturnType<typeof useQuery<TeamSummary[]>>;
  selectedTeam: TeamSummary | null;
  selectedTeamId: string;
  onSelectTeam: (id: string) => void;
}

function SettingsTab({
  teams,
  teamsQuery,
  selectedTeam,
  selectedTeamId,
  onSelectTeam,
}: SettingsTabProps) {
  const { t } = useTranslation();
  const copy = t.teams;
  const queryClient = useQueryClient();
  const [teamName, setTeamName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [docPath, setDocPath] = useState("notes.md");
  const [docContent, setDocContent] = useState("");
  const [editingDoc, setEditingDoc] = useState<TeamDocumentSummary | null>(null);
  const [editingBinary, setEditingBinary] = useState(false);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [previewDoc, setPreviewDoc] = useState<TeamDocumentSummary | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const pendingInvitesQuery = useQuery({
    queryKey: ["team-pending-invites"],
    queryFn: api.listPendingInvites,
  });

  const teamQuery = useQuery({
    queryKey: ["team", selectedTeamId],
    queryFn: () => api.getTeam(selectedTeamId),
    enabled: Boolean(selectedTeamId),
  });
  const invitesQuery = useQuery({
    queryKey: ["team-invites", selectedTeamId],
    queryFn: () => api.listTeamInvites(selectedTeamId),
    enabled: Boolean(selectedTeamId),
  });
  const docsQuery = useQuery({
    queryKey: ["team-documents", selectedTeamId],
    queryFn: () => api.listTeamDocuments(selectedTeamId),
    enabled: Boolean(selectedTeamId),
  });

  const createTeamMutation = useMutation({
    mutationFn: () => api.createTeam(teamName.trim()),
    onSuccess: (team: TeamSummary) => {
      setTeamName("");
      onSelectTeam(team.id);
      setNotice({ tone: "ok", text: copy.notices.teamCreated });
      queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.teamCreateFailed)),
  });

  const inviteMutation = useMutation({
    mutationFn: () => api.createTeamInvite(selectedTeamId, inviteEmail.trim()),
    onSuccess: () => {
      setInviteEmail("");
      setNotice({ tone: "ok", text: copy.notices.inviteCreated });
      queryClient.invalidateQueries({ queryKey: ["team-invites", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.inviteFailed)),
  });

  const respondInviteMutation = useMutation({
    mutationFn: ({ inviteId, action }: { inviteId: string; action: "accept" | "reject" }) =>
      api.respondInvite(inviteId, action),
    onSuccess: () => {
      setNotice({ tone: "ok", text: copy.notices.inviteResponded });
      queryClient.invalidateQueries({ queryKey: ["team-pending-invites"] });
      queryClient.invalidateQueries({ queryKey: ["teams"] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.inviteRespondFailed)),
  });

  const cancelInviteMutation = useMutation({
    mutationFn: (inviteId: string) => api.cancelTeamInvite(selectedTeamId, inviteId),
    onSuccess: () => {
      setNotice({ tone: "ok", text: copy.notices.inviteCancelled });
      queryClient.invalidateQueries({ queryKey: ["team-invites", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.inviteCancelFailed)),
  });

  const createDocMutation = useMutation({
    mutationFn: () =>
      api.createTeamDocument(selectedTeamId, { path: docPath.trim(), content: docContent }),
    onSuccess: () => {
      resetEditor();
      setNotice({ tone: "ok", text: copy.notices.docSaved });
      queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.docSaveFailed)),
  });

  const updateDocMutation = useMutation({
    mutationFn: () =>
      api.updateTeamDocument(selectedTeamId, editingDoc?.id ?? "", {
        content: docContent,
        parent_hash: editingDoc?.content_hash,
      }),
    onSuccess: () => {
      resetEditor();
      setNotice({ tone: "ok", text: copy.notices.docUpdated });
      queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.docUpdateFailed)),
  });

  const deleteDocMutation = useMutation({
    mutationFn: (docId: string) => api.deleteTeamDocument(selectedTeamId, docId),
    onSuccess: () => {
      setNotice({ tone: "ok", text: copy.notices.docDeleted });
      queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
    },
    onError: (error: unknown) => setNotice(toError(error, copy.notices.docDeleteFailed)),
  });

  const docs = docsQuery.data ?? [];

  const resetEditor = () => {
    setEditingDoc(null);
    setEditingBinary(false);
    setDocPath("notes.md");
    setDocContent("");
  };

  const selectDocument = async (doc: TeamDocumentSummary) => {
    setEditingDoc(doc);
    setDocPath(doc.path);
    if (doc.is_binary) {
      setEditingBinary(true);
      setDocContent("");
      setNotice(null);
      return;
    }
    setEditingBinary(false);
    setLoadingDoc(true);
    setDocContent("");
    try {
      const detail = await api.getTeamDocument(selectedTeamId, doc.id);
      if (detail.is_binary) {
        setEditingBinary(true);
        setDocContent("");
      } else {
        setDocContent(detail.content ?? "");
      }
      setNotice(null);
    } catch (error) {
      setNotice(toError(error, copy.notices.docLoadFailed));
    } finally {
      setLoadingDoc(false);
    }
  };

  const uploadFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (list.length === 0 || !selectedTeamId) return;
    setUploading(true);
    let ok = 0;
    try {
      // Sequential: the Pi backend distills/embeds on write — parallel uploads
      // would just queue behind each other and spike load.
      for (const file of list) {
        try {
          await api.uploadTeamFile(selectedTeamId, file, file.name);
          ok += 1;
        } catch (error) {
          setNotice(toError(error, `'${file.name}' ${copy.notices.uploadFailedPrefix}`));
        }
      }
      if (ok > 0) {
        setNotice({ tone: "ok", text: `${ok}${copy.notices.uploadedCountSuffix}` });
        queryClient.invalidateQueries({ queryKey: ["team-documents", selectedTeamId] });
      }
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      {/* Compact top row: create-team form sits inline at the top of the tab. */}
      <div className="mb-3 flex items-center justify-end">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!teamName.trim())
              return setNotice({ tone: "error", text: copy.notices.teamNameRequired });
            createTeamMutation.mutate();
          }}
        >
          <Input
            value={teamName}
            onChange={(event) => setTeamName(event.target.value)}
            placeholder={copy.page.newTeamPlaceholder}
            aria-label={copy.page.newTeamAriaLabel}
            className="h-8 w-40 text-sm"
          />
          <Button type="submit" size="sm" disabled={createTeamMutation.isPending}>
            {copy.page.create}
          </Button>
        </form>
      </div>
      {notice && (
        <div
          className={`mb-4 rounded-xl border px-4 py-3 text-sm ${
            notice.tone === "error" ? "border-destructive/30 text-destructive" : "text-muted-foreground"
          }`}
        >
          {notice.text}
        </div>
      )}

      <div className="flex w-full min-w-0 flex-col gap-4 lg:grid lg:items-start lg:gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="w-full min-w-0 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <UsersRound className="size-4" /> {copy.page.myTeams}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {teamsQuery.isLoading ? (
                [1, 2, 3].map((item) => <Skeleton key={item} className="h-12 rounded-xl" />)
              ) : teams.length === 0 ? (
                <EmptyState icon={UsersRound} text={copy.page.noTeams} />
              ) : (
                teams.map((team) => (
                  <button
                    key={team.id}
                    type="button"
                    onClick={() => onSelectTeam(team.id)}
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
                <Inbox className="size-4" /> {copy.page.receivedInvites}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(pendingInvitesQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">{copy.page.noPendingInvites}</p>
              ) : (
                pendingInvitesQuery.data?.map((invite) => (
                  <div key={invite.id} className="rounded-xl border p-3">
                    <p className="text-sm font-medium">{invite.team_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {copy.page.expiresPrefix} {new Date(invite.expires_at).toLocaleDateString("ko-KR")}
                    </p>
                    <div className="mt-3 flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => respondInviteMutation.mutate({ inviteId: invite.id, action: "accept" })}
                      >
                        {copy.page.accept}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => respondInviteMutation.mutate({ inviteId: invite.id, action: "reject" })}
                      >
                        {copy.page.reject}
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </aside>

        <section className="w-full min-w-0 space-y-4">
          {!selectedTeam ? (
            <NoTeamHint text={copy.page.pickTeamHint} />
          ) : (
            <>
              <Card>
                <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <CardTitle className="truncate">
                      {teamQuery.data?.name ?? selectedTeam.name}
                    </CardTitle>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {teamQuery.data?.members.length ?? 0}
                      {copy.members.countSuffix}
                    </p>
                  </div>
                  {/* Condensed: refresh is icon-only with a title; primary
                      actions keep their labels. */}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      title={copy.page.refresh}
                      aria-label={copy.page.refresh}
                      onClick={() => {
                        teamsQuery.refetch();
                        teamQuery.refetch();
                        docsQuery.refetch();
                        invitesQuery.refetch();
                      }}
                    >
                      <RefreshCcw className="size-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="grid w-full gap-4 md:grid-cols-2 md:items-stretch">
                  <div className="flex w-full min-w-0 flex-col gap-2">
                    <Label>{copy.page.members}</Label>
                    <div className="flex w-full flex-1 flex-col gap-1.5 rounded-xl border p-3">
                      {teamQuery.data?.members.map((member) => (
                        <div
                          key={member.user_id}
                          className="flex w-full items-center justify-between gap-3 rounded-lg bg-muted/30 px-3 py-1.5"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium">{member.email}</p>
                            <p className="truncate text-[10px] text-muted-foreground">
                              {member.user_id}
                            </p>
                          </div>
                          <Badge
                            variant={member.role === "owner" ? "default" : "secondary"}
                            className="shrink-0"
                          >
                            {member.role}
                          </Badge>
                        </div>
                      )) ?? <Skeleton className="h-12 rounded-lg" />}
                    </div>
                  </div>

                  <div className="flex w-full min-w-0 flex-col gap-2">
                    <Label htmlFor="team-invite">{copy.page.inviteByEmail}</Label>
                    <form
                      className="flex w-full flex-1 flex-col gap-3 rounded-xl border p-3"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!inviteEmail.trim())
                          return setNotice({ tone: "error", text: copy.notices.inviteEmailRequired });
                        inviteMutation.mutate();
                      }}
                    >
                      <div className="flex min-w-0 gap-2">
                        <Input
                          id="team-invite"
                          type="email"
                          value={inviteEmail}
                          onChange={(event) => setInviteEmail(event.target.value)}
                          placeholder="teammate@example.com"
                          className="min-w-0 flex-1"
                        />
                        <Button type="submit" disabled={inviteMutation.isPending}>
                          <MailPlus className="size-4" />
                        </Button>
                      </div>

                      <div className="flex flex-1 flex-col gap-1.5 overflow-hidden">
                        <p className="text-xs font-medium text-muted-foreground">{copy.page.sentInvites}</p>
                        {(invitesQuery.data ?? []).length > 0 ? (
                          <div className="flex flex-col gap-1.5">
                            {(invitesQuery.data ?? []).slice(0, 4).map((invite) => (
                              <div
                                key={invite.id}
                                className="flex items-center justify-between gap-3 rounded-lg bg-muted/30 px-3 py-1.5"
                              >
                                <p className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                                  {invite.invitee_email}
                                </p>
                                <div className="flex shrink-0 items-center gap-1">
                                  <Badge variant="outline">{invite.status}</Badge>
                                  {invite.status === "pending" && (
                                    <Button
                                      type="button"
                                      variant="outline"
                                      size="icon"
                                      className="size-7"
                                      title={copy.page.cancelInvite}
                                      aria-label={copy.page.cancelInvite}
                                      disabled={cancelInviteMutation.isPending}
                                      onClick={() => cancelInviteMutation.mutate(invite.id)}
                                    >
                                      <X className="size-4" />
                                    </Button>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground">{copy.page.noSentInvites}</p>
                        )}
                      </div>
                    </form>
                  </div>
                </CardContent>
              </Card>

              <div className="grid gap-4 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
                <Card>
                  <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <FileText className="size-4" /> {copy.docs.title}
                    </CardTitle>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={uploading}
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <Upload className="me-2 size-4" /> {copy.docs.upload}
                      </Button>
                      <Button
                        asChild
                        type="button"
                        variant="outline"
                        size="icon"
                        title={copy.docs.downloadZip}
                        aria-label={copy.docs.downloadZip}
                      >
                        <a href={api.teamExportZipUrl(selectedTeam.id)}>
                          <FileArchive className="size-4" />
                        </a>
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {/* hidden picker — drives both the button and the drop zone */}
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      className="hidden"
                      onChange={(event) => {
                        if (event.target.files) uploadFiles(event.target.files);
                        event.target.value = "";
                      }}
                    />
                    <div
                      onDragOver={(event) => {
                        event.preventDefault();
                        setDragActive(true);
                      }}
                      onDragLeave={() => setDragActive(false)}
                      onDrop={(event) => {
                        event.preventDefault();
                        setDragActive(false);
                        if (event.dataTransfer.files) uploadFiles(event.dataTransfer.files);
                      }}
                      className={`rounded-xl border border-dashed px-3 py-4 text-center text-xs transition-colors ${
                        dragActive ? "border-primary bg-primary/5 text-foreground" : "text-muted-foreground"
                      }`}
                    >
                      {uploading ? copy.docs.uploading : copy.docs.dropHint}
                    </div>
                    {docsQuery.isLoading ? (
                      [1, 2, 3].map((item) => <Skeleton key={item} className="h-14 rounded-xl" />)
                    ) : docs.length === 0 ? (
                      <EmptyState icon={FileText} text={copy.docs.empty} />
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
                            <div className="flex min-w-0 flex-1 items-start gap-2">
                              {doc.is_binary ? (
                                <FileIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                              ) : (
                                <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                              )}
                              <div className="min-w-0 flex-1 space-y-1">
                                <p className="break-all text-sm font-medium">{doc.path}</p>
                                <div className="flex flex-wrap items-center gap-1.5">
                                  <Badge variant="secondary" className="font-normal">
                                    {fileTypeLabel(copy.fileTypes, doc.path, doc.mime, doc.is_binary)}
                                  </Badge>
                                  <span className="text-xs text-muted-foreground">v{doc.version}</span>
                                  {doc.size != null && (
                                    <span className="text-xs text-muted-foreground">
                                      {humanizeSize(doc.size)}
                                    </span>
                                  )}
                                </div>
                                {(doc.uploader_email || doc.updated_by_email) && (
                                  <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px]">
                                    {doc.uploader_email && (
                                      <EmailChip label={copy.page.uploaderLabel} email={doc.uploader_email} />
                                    )}
                                    {doc.updated_by_email && (
                                      <EmailChip label={copy.page.updatedByLabel} email={doc.updated_by_email} />
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-1">
                              {isViewable(doc.path, doc.mime) ? (
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setPreviewDoc(doc);
                                  }}
                                  className="inline-flex size-8 items-center justify-center rounded-md border hover:bg-accent"
                                  aria-label={copy.docs.openAriaLabel}
                                  title={copy.docs.openTitle}
                                >
                                  <ExternalLink className="size-4" />
                                </button>
                              ) : (
                                <a
                                  href={api.teamDocumentRawUrl(selectedTeam.id, doc.id)}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(event) => event.stopPropagation()}
                                  className="inline-flex size-8 items-center justify-center rounded-md border hover:bg-accent"
                                  aria-label={copy.docs.downloadAriaLabel}
                                  title={copy.docs.downloadTitle}
                                >
                                  <Download className="size-4" />
                                </a>
                              )}
                              <Button
                                type="button"
                                variant="outline"
                                size="icon"
                                className="size-8"
                                title={copy.docs.deleteDoc}
                                aria-label={copy.docs.deleteDoc}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  deleteDocMutation.mutate(doc.id);
                                }}
                              >
                                <Trash2 className="size-4" />
                              </Button>
                            </div>
                          </div>
                        </button>
                      ))
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">{editingDoc ? copy.docs.editTitle : copy.docs.newTitle}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {editingDoc && editingBinary ? (
                      <div className="space-y-4">
                        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed py-10 text-center">
                          <FileIcon className="size-8 text-muted-foreground" />
                          <div className="space-y-1">
                            <p className="break-all text-sm font-medium">{editingDoc.path}</p>
                            <p className="text-xs text-muted-foreground">
                              {isViewable(editingDoc.path, editingDoc.mime)
                                ? copy.docs.viewableHint
                                : copy.docs.nonViewableHint}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {fileTypeLabel(copy.fileTypes, editingDoc.path, editingDoc.mime, true)} ·{" "}
                              {humanizeSize(editingDoc.size)}
                            </p>
                          </div>
                          {isViewable(editingDoc.path, editingDoc.mime) ? (
                            <Button type="button" onClick={() => setPreviewDoc(editingDoc)}>
                              <ExternalLink className="me-2 size-4" /> {copy.docs.open}
                            </Button>
                          ) : (
                            <a
                              href={api.teamDocumentRawUrl(selectedTeam.id, editingDoc.id)}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                            >
                              <Download className="me-2 size-4" /> {copy.docs.download}
                            </a>
                          )}
                        </div>
                        <div className="flex justify-end">
                          <Button type="button" variant="outline" onClick={resetEditor}>
                            {copy.docs.switchToNew}
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <form
                        className="space-y-4"
                        onSubmit={(event) => {
                          event.preventDefault();
                          if (!docPath.trim())
                            return setNotice({ tone: "error", text: copy.notices.docPathRequired });
                          if (editingDoc) updateDocMutation.mutate();
                          else createDocMutation.mutate();
                        }}
                      >
                        <div className="space-y-2">
                          <Label htmlFor="team-doc-path">{copy.docs.pathLabel}</Label>
                          <Input
                            id="team-doc-path"
                            value={docPath}
                            disabled={Boolean(editingDoc)}
                            onChange={(event) => setDocPath(event.target.value)}
                            placeholder={copy.docs.pathPlaceholder}
                          />
                        </div>
                        <div className="space-y-2">
                          <Label htmlFor="team-doc-content">{copy.docs.contentLabel}</Label>
                          <textarea
                            id="team-doc-content"
                            value={docContent}
                            disabled={loadingDoc}
                            onChange={(event) => setDocContent(event.target.value)}
                            placeholder={loadingDoc ? copy.docs.contentLoading : copy.docs.contentPlaceholder}
                            className="min-h-64 w-full rounded-xl border bg-background px-3 py-2 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
                          />
                        </div>
                        <div className="flex flex-wrap justify-end gap-2">
                          {editingDoc && (
                            <Button type="button" variant="outline" onClick={resetEditor}>
                              {copy.docs.switchToNew}
                            </Button>
                          )}
                          <Button type="submit" disabled={createDocMutation.isPending || updateDocMutation.isPending}>
                            {editingDoc ? copy.docs.update : copy.docs.save}
                          </Button>
                        </div>
                      </form>
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </section>
      </div>

      <DocPreviewDialog teamId={selectedTeamId} doc={previewDoc} onClose={() => setPreviewDoc(null)} />
    </>
  );
}

// ---------------------------------------------------------------------------
// 맥락지도 tab: the context-map graph (inline) + node-info popup.
// ---------------------------------------------------------------------------

function MapTab({ teamId }: { teamId: string }) {
  const { t } = useTranslation();
  const copy = t.teams.wiki;
  const tabsCopy = t.teams.tabs;
  const workspaceQuery = useQuery({
    queryKey: ["team-workspace", teamId],
    queryFn: () => api.getTeamWorkspace(teamId),
    enabled: Boolean(teamId),
  });
  const articlesQuery = useQuery({
    queryKey: ["team-wiki-articles", teamId],
    queryFn: () => api.listTeamWikiArticles(teamId),
    enabled: Boolean(teamId),
  });
  const articles = articlesQuery.data ?? [];
  const [activeNode, setActiveNode] = useState<GraphNode | null>(null);

  const activeNodeArticle = useMemo(() => {
    if (!activeNode) return null;
    const lower = activeNode.label.toLowerCase();
    return articles.find((a) => a.title.toLowerCase() === lower) ?? null;
  }, [activeNode, articles]);

  const graph = workspaceQuery.data?.graph;
  const hasGraph = Boolean(graph && (graph.nodes as GraphNode[]).length > 0);

  return (
    <>
      <p className="mb-3 text-sm text-muted-foreground">{tabsCopy.mapHint}</p>
      {workspaceQuery.isLoading ? (
        <Skeleton className="h-[60vh] min-h-[360px] w-full rounded-xl" />
      ) : hasGraph ? (
        <WikiMiniMap
          nodes={graph!.nodes as GraphNode[]}
          edges={graph!.edges as never}
          onNodeClick={setActiveNode}
          inline
        />
      ) : (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center text-muted-foreground">
          <MapIcon className="size-8" />
          <p className="text-sm">{tabsCopy.mapEmpty}</p>
        </div>
      )}

      <Dialog open={Boolean(activeNode)} onOpenChange={(open) => !open && setActiveNode(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="break-words">{activeNode?.label}</DialogTitle>
          </DialogHeader>
          {activeNode && (
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{t.teams.nodeKinds[activeNode.kind] ?? activeNode.kind}</Badge>
                {activeNode.version != null && (
                  <span className="text-xs text-muted-foreground">v{activeNode.version}</span>
                )}
              </div>
              {activeNode.path && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">{copy.nodePathLabel}</p>
                  <p className="break-all font-mono text-xs">{activeNode.path}</p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setActiveNode(null)}>
              {copy.close}
            </Button>
            {(activeNode?.kind === "doc" || activeNode?.kind === "note") &&
              activeNode.download_url &&
              (nodeViewable(activeNode) ? (
                <Button asChild>
                  <a href={activeNode.download_url} target="_blank" rel="noreferrer">
                    <ExternalLink className="me-2 size-4" /> {copy.open}
                  </a>
                </Button>
              ) : (
                <Button asChild>
                  <a href={activeNode.download_url} target="_blank" rel="noreferrer">
                    <Download className="me-2 size-4" /> {copy.download}
                  </a>
                </Button>
              ))}
            {activeNodeArticle && (
              <Button asChild variant="secondary">
                <a href={`/teams/wiki?id=${teamId}`}>
                  <BookOpen className="me-2 size-4" /> {copy.openInWiki}
                </a>
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
