"use client";

import { FileText } from "lucide-react";
import type { VaultNote } from "@/lib/types";
import { useTranslation } from "@/lib/i18n";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

interface VaultNoteDetailProps {
  note: VaultNote | null;
}

export function VaultNoteDetail({ note }: VaultNoteDetailProps) {
  const { t } = useTranslation();
  if (!note) {
    return (
      <Card className="flex min-h-[400px] items-center justify-center">
        <div className="text-center text-muted-foreground">
          <FileText className="mx-auto mb-3 size-8" />
          <p className="text-sm">{t.vaultNote.selectNote}</p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader>
        <CardTitle className="break-words">{note.title}</CardTitle>
        <div className="flex flex-wrap gap-1.5 pt-2">
          {note.tags.map((tag) => (
            <Badge key={tag} variant="secondary" className="break-all">
              #{tag}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4 break-all rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
          {note.path}
        </div>
        <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md border bg-muted/50 p-4 text-sm">
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
      </CardContent>
    </Card>
  );
}
