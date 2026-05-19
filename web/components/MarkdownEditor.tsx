"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

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
}: MarkdownEditorProps) {
  // Pull current theme from the html data-color-mode attribute so the editor
  // matches the rest of the app without a custom theme prop.
  const [colorMode, setColorMode] = useState<"light" | "dark">("light");
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

  return (
    <div data-color-mode={colorMode}>
      <MDEditor
        value={value}
        onChange={(next) => onChange(next ?? "")}
        height={height}
        preview={hidePreview ? "edit" : "live"}
        visibleDragbar={false}
        textareaProps={{ readOnly }}
      />
    </div>
  );
}
