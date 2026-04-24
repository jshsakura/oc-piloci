"use client";

import { FileText } from "lucide-react";
import type { VaultNote } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

interface VaultNoteDetailProps {
  note: VaultNote | null;
}

export function VaultNoteDetail({ note }: VaultNoteDetailProps) {
  if (!note) {
    return (
      <Card className="flex min-h-[400px] items-center justify-center">
        <div className="text-center text-muted-foreground">
          <FileText className="mx-auto mb-3 size-8" />
          <p className="text-sm">노트를 선택하세요</p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{note.title}</CardTitle>
        <div className="flex flex-wrap gap-1.5 pt-2">
          {note.tags.map((tag) => (
            <Badge key={tag} variant="secondary">#{tag}</Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-4 rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
          {note.path}
        </div>
        <pre className="max-h-[400px] overflow-y-auto whitespace-pre-wrap break-words rounded-md border bg-muted/50 p-4 text-sm">
          {note.markdown}
        </pre>

        {note.links.length > 0 && (
          <>
            <Separator className="my-4" />
            <div>
              <p className="mb-2 text-sm font-medium text-muted-foreground">연결된 노트</p>
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
