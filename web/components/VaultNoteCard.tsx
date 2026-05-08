"use client";

import { Hash, Link2 } from "lucide-react";
import type { VaultNote } from "@/lib/types";
import { useTranslation } from "@/lib/i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface VaultNoteCardProps {
  note: VaultNote;
  active?: boolean;
  onSelect: (note: VaultNote) => void;
}

export function VaultNoteCard({ note, active = false, onSelect }: VaultNoteCardProps) {
  const { t } = useTranslation();
  return (
    <Card
      className={`min-w-0 cursor-pointer overflow-hidden transition-shadow hover:shadow-md ${active ? "ring-2 ring-inset ring-primary" : ""}`}
      onClick={() => onSelect(note)}
    >
      <CardContent className="p-5">
        <div className="mb-2 flex items-start justify-between gap-2">
          <h3 className="min-w-0 flex-1 break-words font-semibold">{note.title}</h3>
          <Badge variant="outline" className="shrink-0">
            {note.tags.length} {t.vaultNote.tags}
          </Badge>
        </div>
        <p className="mb-3 line-clamp-2 break-words text-sm text-muted-foreground">
          {note.excerpt || t.vaultNote.noPreview}
        </p>
        {note.tags.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {note.tags.slice(0, 4).map((tag) => (
              <Badge key={tag} variant="secondary" className="break-all text-xs">
                #{tag}
              </Badge>
            ))}
            {note.tags.length > 4 && (
              <Badge variant="secondary" className="text-xs">+{note.tags.length - 4}</Badge>
            )}
          </div>
        )}
        <div className="flex items-center gap-4 border-t pt-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <Hash className="size-3" /> {note.tags.length}
          </span>
          <span className="inline-flex items-center gap-1">
            <Link2 className="size-3" /> {note.links.length}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
