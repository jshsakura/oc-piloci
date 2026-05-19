"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { csrfHeaders } from "@/lib/api";

// react-md-editor uses browser-only APIs (clipboard, draggable handles).
// SSR is a no-go; we lazy-load it so the static bundle stays slim.
const MDEditor = dynamic(() => import("@uiw/react-md-editor"), { ssr: false });

interface MarkdownEditorProps {
  value: string;
  onChange: (next: string) => void;
  /** Visual height of the edit pane in px. Default ~360 for modal use. */
  height?: number;
  /** Hides the live preview pane — saves horizontal space in narrow drawers. */
  hidePreview?: boolean;
  /** Disables editing (read-only display). */
  readOnly?: boolean;
  /** When set, pasting/dropping images uploads them to this endpoint and
   *  inserts the returned markdown link at the cursor. Without it, image
   *  paste is dropped silently. */
  imageUploadUrl?: string;
}

// 5MB ceiling matches the server's body cap. Down-scale anything bigger.
const MAX_PIXELS_PER_SIDE = 1600;
const WEBP_QUALITY = 0.85;

async function blobToWebp(file: Blob): Promise<Blob> {
  // Decode → potentially down-scale → re-encode as WebP. Off-main-thread
  // would be nicer but canvas2d only runs on the main thread anyway and
  // the work is short for typical pasted screenshots.
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const i = new Image();
    i.onload = () => {
      URL.revokeObjectURL(url);
      resolve(i);
    };
    i.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("이미지 디코드 실패"));
    };
    i.src = url;
  });

  const ratio = Math.min(1, MAX_PIXELS_PER_SIDE / Math.max(img.width, img.height));
  const w = Math.round(img.width * ratio);
  const h = Math.round(img.height * ratio);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 컨텍스트 못 잡음");
  ctx.drawImage(img, 0, 0, w, h);

  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("WebP 인코딩 실패"))),
      "image/webp",
      WEBP_QUALITY,
    );
  });
}

async function uploadImage(url: string, blob: Blob): Promise<string> {
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "image/webp", ...csrfHeaders("POST") },
    body: blob,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: "이미지 업로드 실패" }));
    throw new Error((err as { error?: string }).error || `업로드 실패 ${res.status}`);
  }
  const data = (await res.json()) as { url: string };
  return data.url;
}

/**
 * Thin wrapper around ``@uiw/react-md-editor`` so the rest of the app
 * doesn't have to know about the dynamic import or theme detection. Pass
 * a controlled value/onChange like any textarea — the editor handles
 * undo, drag-drop images (when enabled), and CodeMirror-style shortcuts.
 *
 * Theme follows the page's color scheme: ``data-color-mode="dark"`` on
 * <html> from next-themes flips the editor to dark too.
 */
export function MarkdownEditor({
  value,
  onChange,
  height = 360,
  hidePreview = false,
  readOnly = false,
  imageUploadUrl,
}: MarkdownEditorProps) {
  // Pull current theme from the html data-color-mode attribute so the editor
  // matches the rest of the app without a custom theme prop.
  const [colorMode, setColorMode] = useState<"light" | "dark">("light");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const update = () => {
      const dark = document.documentElement.classList.contains("dark");
      setColorMode(dark ? "dark" : "light");
    };
    update();
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);

  // Look up the live textarea each call — react-md-editor lazy-mounts it.
  const insertAtCursor = useCallback(
    (snippet: string) => {
      const root = containerRef.current;
      const ta = root?.querySelector("textarea") as HTMLTextAreaElement | null;
      if (!ta) {
        onChange(value + snippet);
        return;
      }
      const start = ta.selectionStart ?? value.length;
      const end = ta.selectionEnd ?? value.length;
      const next = value.slice(0, start) + snippet + value.slice(end);
      onChange(next);
      // Restore cursor just after inserted snippet on next tick.
      requestAnimationFrame(() => {
        const pos = start + snippet.length;
        ta.setSelectionRange(pos, pos);
        ta.focus();
      });
    },
    [value, onChange],
  );

  const handleImageBlobs = useCallback(
    async (blobs: Blob[]) => {
      if (!imageUploadUrl || blobs.length === 0) return;
      setUploading(true);
      setUploadError(null);
      try {
        for (const raw of blobs) {
          const webp = await blobToWebp(raw);
          const url = await uploadImage(imageUploadUrl, webp);
          insertAtCursor(`\n![](${url})\n`);
        }
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : "이미지 업로드 실패");
      } finally {
        setUploading(false);
      }
    },
    [imageUploadUrl, insertAtCursor],
  );

  // Paste/drop are attached to the wrapper because react-md-editor doesn't
  // expose textarea-level events. capture phase catches the event before
  // the library's own default-handler swallows the data.
  useEffect(() => {
    const root = containerRef.current;
    if (!root || !imageUploadUrl) return;

    const onPaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items ?? [];
      const blobs: Blob[] = [];
      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        if (it.type.startsWith("image/")) {
          const f = it.getAsFile();
          if (f) blobs.push(f);
        }
      }
      if (blobs.length === 0) return;
      e.preventDefault();
      void handleImageBlobs(blobs);
    };

    const onDrop = (e: DragEvent) => {
      const files = Array.from(e.dataTransfer?.files ?? []).filter((f) =>
        f.type.startsWith("image/"),
      );
      if (files.length === 0) return;
      e.preventDefault();
      void handleImageBlobs(files);
    };
    const onDragOver = (e: DragEvent) => {
      if (Array.from(e.dataTransfer?.types ?? []).includes("Files")) e.preventDefault();
    };

    root.addEventListener("paste", onPaste);
    root.addEventListener("drop", onDrop);
    root.addEventListener("dragover", onDragOver);
    return () => {
      root.removeEventListener("paste", onPaste);
      root.removeEventListener("drop", onDrop);
      root.removeEventListener("dragover", onDragOver);
    };
  }, [handleImageBlobs, imageUploadUrl]);

  return (
    <div ref={containerRef} data-color-mode={colorMode} className="relative">
      <MDEditor
        value={value}
        onChange={(next) => onChange(next ?? "")}
        height={height}
        preview={hidePreview ? "edit" : "live"}
        visibleDragbar={false}
        textareaProps={{ readOnly }}
      />
      {imageUploadUrl && (uploading || uploadError) && (
        <div className="pointer-events-none absolute inset-x-2 bottom-2 rounded-md bg-background/95 px-3 py-1.5 text-xs shadow-md backdrop-blur">
          {uploading ? (
            <span className="text-muted-foreground">이미지를 WebP로 변환·업로드 중…</span>
          ) : (
            <span className="text-destructive">{uploadError}</span>
          )}
        </div>
      )}
      {imageUploadUrl && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          이미지를 붙여넣거나 끌어다 놓으면 WebP로 자동 변환·업로드돼요.
        </p>
      )}
    </div>
  );
}
