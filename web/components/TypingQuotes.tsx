"use client";

import { useState, useEffect, useCallback } from "react";

interface TypingQuotesProps {
  quotes: readonly string[];
  typingSpeed?: number;
  deletingSpeed?: number;
  pauseDuration?: number;
}

export default function TypingQuotes({
  quotes,
  typingSpeed = 50,
  deletingSpeed = 25,
  pauseDuration = 4000,
}: TypingQuotesProps) {
  const [index, setIndex] = useState(0);
  const [text, setText] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);

  const tick = useCallback(() => {
    const current = quotes[index];
    if (!current) return;

    if (!isDeleting) {
      setText(current.slice(0, text.length + 1));
      if (text.length + 1 === current.length) {
        return { pause: true };
      }
    } else {
      setText(current.slice(0, text.length - 1));
      if (text.length <= 1) {
        setIndex((i) => (i + 1) % quotes.length);
        setIsDeleting(false);
        return { pause: false };
      }
    }
    return { pause: false };
  }, [text, index, isDeleting, quotes]);

  useEffect(() => {
    if (!quotes[index]) return;

    let timeout: NodeJS.Timeout;

    if (!isDeleting && text === quotes[index]) {
      timeout = setTimeout(() => setIsDeleting(true), pauseDuration);
    } else if (isDeleting && text === "") {
      setIndex((i) => (i + 1) % quotes.length);
      setIsDeleting(false);
    } else {
      const speed = isDeleting ? deletingSpeed : typingSpeed;
      timeout = setTimeout(() => {
        const current = quotes[index];
        if (!current) return;
        if (isDeleting) {
          setText(current.slice(0, text.length - 1));
        } else {
          setText(current.slice(0, text.length + 1));
        }
      }, speed);
    }

    return () => clearTimeout(timeout);
  }, [text, index, isDeleting, quotes, typingSpeed, deletingSpeed, pauseDuration]);

  return (
    <span className="inline-flex items-center">
      <span>{text}</span>
      <span className="ml-0.5 inline-block w-[2px] animate-[blink_0.8s_step-end_infinite] bg-foreground/60 h-[1em]" />
    </span>
  );
}
