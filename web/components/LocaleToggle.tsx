"use client";

import { useState } from "react";
import { Globe, Check } from "lucide-react";
import { useTranslation } from "@/lib/i18n";
import { locales, localeLabels } from "@/lib/copy";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export default function LocaleToggle() {
  const { locale, setLocale, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const copy = t.appShell.locale;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={copy.trigger}
        >
          <Globe className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.desc}</DialogDescription>
        </DialogHeader>
        <div className="mt-2 grid gap-1.5">
          {locales.map((code) => {
            const active = code === locale;
            const label = localeLabels[code];
            return (
              <button
                key={code}
                type="button"
                onClick={() => {
                  setLocale(code);
                  setOpen(false);
                }}
                className={`flex items-center justify-between rounded-md border px-3 py-2.5 text-left transition-colors hover:bg-accent ${
                  active ? "border-primary bg-accent" : "border-border"
                }`}
              >
                <span className="flex flex-col">
                  <span className="text-sm font-medium">{label.native}</span>
                  <span className="text-xs text-muted-foreground">{label.short}</span>
                </span>
                {active && <Check className="size-4 text-primary" />}
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
