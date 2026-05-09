"use client";

import { FileText } from "lucide-react";
import type { VaultNote } from "@/lib/types";
import { useTranslation } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

interface VaultNoteDetailProps {
  note: VaultNote | null;
}

export function VaultNoteDetail({ note }: VaultNoteDetailProps) {
  const { t } = useTranslation();
  if (!note) {
    return (
      <div className="flex h-full min-h-[300px] items-center justify-center text-muted-foreground">
        <div className="text-center">
          <FileText className="mx-auto mb-3 size-8" />
          <p className="text-sm">{t.vaultNote.selectNote}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0 p-5">
      <h2 className="break-words text-lg font-semibold leading-tight">{note.title}</h2>
      {note.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {note.tags.map((tag) => (
            <Badge key={tag} variant="secondary" className="break-all">
              #{tag}
            </Badge>
          ))}
        </div>
      )}
      <div className="mt-4 break-all rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
        {note.path}
      </div>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-all rounded-md border bg-muted/50 p-4 text-sm">
        {note.markdown ?? note.excerpt}
      </pre>

      {note.links.length > 0 && (
        <>
          <Separator className="my-4" />
          <div>
            <p className="mb-2 text-sm font-medium text-muted-foreground">{t.vaultNote.linkedNotes}</p>
            <div className="flex flex-wrap gap-1.5">
              {note.links.map((link) => (
                <Badge key={link} variant="outline">{link}</Badge>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
