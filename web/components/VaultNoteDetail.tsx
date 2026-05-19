"use client";

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Clock } from "lucide-react";
import type { VaultNote } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { relTimeKr } from "@/lib/time";

interface VaultNoteDetailProps {
  note: VaultNote | null;
  /** Called when the user clicks a `[[wikilink]]` inside the body. The
   *  parent decides what to do — typically: open the matching note, fall
   *  back to a tag filter, or no-op. */
  onWikilinkClick?: (label: string) => void;
}

/**
 * The curator stores notes as full markdown files with:
 *   - YAML frontmatter at the top (title/memory_id/dates/tags/source)
 *   - the body text
 *   - an appended "## Related" block listing [[tag]] / [[topic]] links
 *
 * That whole package is meant for an LLM consumer, not a reader. Rendering
 * it verbatim was the smoking gun behind "LLM 위키가 어디갔냐" — the page
 * looked like raw markdown source, not a wiki article. This preprocessor:
 *
 *   1. drops the leading frontmatter (we already surface title / tags /
 *      timestamps in the header chrome)
 *   2. drops the trailing auto-Related block (we already render tags as
 *      chips and outbound links as backlinks in the page chrome)
 *   3. rewrites `[[wikilink]]` into a markdown link with a sentinel href
 *      so the <a> component can intercept the click and call the parent
 */
function preprocess(md: string): string {
  const fmStripped = md.replace(/^---\n[\s\S]*?\n---\n+/, "");
  const relStripped = fmStripped.replace(/\n+##\s+Related\s*\n[\s\S]*$/, "");
  return relStripped.replace(/\[\[([^\]]+)\]\]/g, (_, label: string) =>
    `[${label}](#wikilink:${encodeURIComponent(label)})`,
  );
}

export function VaultNoteDetail({ note, onWikilinkClick }: VaultNoteDetailProps) {
  const body = useMemo(
    () => (note ? preprocess(note.markdown ?? note.excerpt ?? "") : ""),
    [note],
  );

  if (!note) return null;

  return (
    <article className="min-w-0">
      <header className="mb-4 space-y-2 border-b pb-3">
        <h2 className="break-words text-xl font-bold leading-tight">{note.title}</h2>
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" />
            {relTimeKr(note.updated_at)} 업데이트
          </span>
          <span className="break-all font-mono opacity-60">{note.path}</span>
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
        {body.trim() ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children, ...rest }) => {
                if (href?.startsWith("#wikilink:")) {
                  const label = decodeURIComponent(href.slice("#wikilink:".length));
                  return (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        onWikilinkClick?.(label);
                      }}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {children}
                    </button>
                  );
                }
                return (
                  <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
                    {children}
                  </a>
                );
              },
            }}
          >
            {body}
          </ReactMarkdown>
        ) : (
          <p className="text-muted-foreground text-sm">아직 본문이 비어 있습니다.</p>
        )}
      </div>
    </article>
  );
}
