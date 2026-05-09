"use client";

import type { VaultNote } from "@/lib/types";
import { useTranslation } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";

interface VaultNoteCardProps {
  note: VaultNote;
  active?: boolean;
  onSelect: (note: VaultNote) => void;
}

export function VaultNoteCard({ note, active = false, onSelect }: VaultNoteCardProps) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={() => onSelect(note)}
      className={`block w-full rounded-lg border bg-card px-3 py-2.5 text-left transition-colors hover:bg-accent/50 ${
        active ? "border-primary bg-accent" : "border-border/60"
      }`}
    >
      <h3 className="line-clamp-2 break-words text-sm font-semibold leading-snug">
        {note.title}
      </h3>
      <p className="mt-1 line-clamp-2 break-words text-xs leading-snug text-muted-foreground">
        {note.excerpt || t.vaultNote.noPreview}
      </p>
      {note.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {note.tags.slice(0, 3).map((tag) => (
            <Badge key={tag} variant="secondary" className="break-all px-1.5 py-0 text-[10px]">
              #{tag}
            </Badge>
          ))}
          {note.tags.length > 3 && (
            <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">+{note.tags.length - 3}</Badge>
          )}
        </div>
      )}
    </button>
  );
}
