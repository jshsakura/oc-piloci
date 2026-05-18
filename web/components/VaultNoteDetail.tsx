"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Clock } from "lucide-react";
import type { VaultNote } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { relTimeKr } from "@/lib/time";

interface VaultNoteDetailProps {
  note: VaultNote | null;
}

export function VaultNoteDetail({ note }: VaultNoteDetailProps) {
  if (!note) return null;

  return (
    <article className="min-w-0">
      <header className="mb-4 space-y-2 border-b pb-3">
        <h2 className="text-xl font-bold leading-tight break-words">{note.title}</h2>
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" />
            {relTimeKr(note.updated_at)} 업데이트
          </span>
          <span className="font-mono opacity-60 break-all">{note.path}</span>
        </div>
        {note.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {note.tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-[10px]">
                #{tag}
              </Badge>
            ))}
          </div>
        )}
      </header>
      <div className="pi-prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {note.markdown ?? note.excerpt}
        </ReactMarkdown>
      </div>
    </article>
  );
}
