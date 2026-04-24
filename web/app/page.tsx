"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  Fingerprint, Code2, Zap, ShieldCheck, BrainCircuit, Network,
  Lock, Plug, ArrowRight, Activity, TrendingDown, Gauge,
  Database, Search, Brain, Heart, Cpu, HardDrive, Microchip,
  MemoryStick, FileJson, Globe,
} from "lucide-react";
import { useAuthStore } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";
import { Locale } from "@/lib/copy";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import BrandMark from "@/components/BrandMark";
import ThemeToggle from "@/components/ThemeToggle";
import TypingQuotes from "@/components/TypingQuotes";

export default function LandingPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { locale, setLocale, t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const [termIdx, setTermIdx] = useState(0);
  const [typed, setTyped] = useState(0);
  const termTimer = useRef<ReturnType<typeof setTimeout>>(null);

  const terminal = t.landing.terminal;
  const ex = terminal.examples[termIdx];

  const termLines = [
    { role: "user", text: ex.q },
    { role: "tool", text: `⚡ ${ex.tool}(${ex.toolArgs})` },
    { role: "result", text: `↳ ${ex.result}` },
    { role: "claude", text: ex.a },
  ];

  const totalChars = termLines.reduce((s, l) => s + l.text.length, 0);

  useEffect(() => {
    if (typed < totalChars) {
      termTimer.current = setTimeout(() => setTyped((c) => c + 1), 22);
    } else {
      termTimer.current = setTimeout(() => {
        setTermIdx((i) => (i + 1) % terminal.examples.length);
        setTyped(0);
      }, 2800);
    }
    return () => { if (termTimer.current) clearTimeout(termTimer.current); };
  }, [typed, totalChars, terminal.examples.length]);

  const copyInstall = () => {
    navigator.clipboard.writeText("uvx oc-piloci install");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  useEffect(() => {
    if (user) router.replace("/dashboard");
  }, [user, router]);

  if (user) return null;

  const features = t.landing.sections.features.list;
  const capabilities = t.landing.sections.capabilities.list;
  const stats = t.landing.stats;

  const featureIcons = [Fingerprint, Code2, Zap, ShieldCheck, BrainCircuit, Network, Lock, Plug];
  const toolIcons = [Database, Search, Brain];
  const engIcons = [Database, HardDrive, Microchip, MemoryStick, FileJson, Globe];

  return (
    <div className="min-h-screen bg-background landing-pattern">
      {/* Nav */}
      <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <BrandMark />
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              asChild
              className="border-primary/30 text-primary hover:bg-primary hover:text-primary-foreground active:bg-primary/80"
            >
              <Link href="/login">{t.common.login}</Link>
            </Button>
            <button
              onClick={() => setLocale(locale === "ko" ? "en" : "ko")}
              className="flex h-8 items-center gap-1 rounded-md border border-border px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <span className={locale === "ko" ? "text-foreground" : ""}>KO</span>
              <span className="text-border">/</span>
              <span className={locale === "en" ? "text-foreground" : ""}>EN</span>
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative mx-auto max-w-6xl px-4 py-16 sm:py-24 text-center overflow-hidden">
        <div className="relative z-10">
          <p className="mb-5 sm:mb-6 h-8 text-xs sm:text-sm font-medium tracking-wide text-muted-foreground">
            <TypingQuotes quotes={t.landing.quotes} />
          </p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl md:text-6xl">
            {t.landing.titleLines[0]}
            <br />
            <span className="text-muted-foreground">
              {t.landing.titleLines[1].split("AI").map((part, i, arr) => (
                <span key={i}>
                  {part}
                  {i < arr.length - 1 && (
                    <span className="bg-clip-text text-transparent animate-[rainbow_4s_linear_infinite] bg-[linear-gradient(90deg,#f87171,#fb923c,#fbbf24,#a3e635,#34d399,#22d3ee,#818cf8,#c084fc,#f87171)] bg-[length:200%_100%]">
                      AI
                    </span>
                  )}
                </span>
              ))}
            </span>
          </h1>

          <div className="mx-auto mt-6 sm:mt-8 max-w-2xl space-y-2">
            {t.landing.descriptionLines.map((line, i) => (
              <motion.p
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.8 + i * 0.5, ease: "easeOut" }}
                className="text-sm sm:text-lg text-muted-foreground"
              >
                {line}
              </motion.p>
            ))}
          </div>

          <div className="mx-auto mt-10 sm:mt-16 grid max-w-md grid-cols-3 gap-3 sm:gap-4">
            {[
              { Icon: Gauge, value: stats.latency, label: stats.latencyLabel },
              { Icon: TrendingDown, value: stats.reduction, label: stats.reductionLabel },
              { Icon: Activity, value: stats.uptime, label: stats.uptimeLabel },
            ].map(({ Icon, value, label }) => (
              <div
                key={label}
                className="group flex flex-col items-center gap-2 rounded-xl border bg-muted/50 px-3 py-4 sm:px-5 sm:py-6 backdrop-blur-sm transition-colors hover:bg-muted"
              >
                <div className="flex size-8 sm:size-10 items-center justify-center rounded-full bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                  <Icon className="size-4 sm:size-5" />
                </div>
                <p className="text-xl sm:text-3xl font-bold tracking-tight">{value}</p>
                <p className="text-[10px] sm:text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
              </div>
            ))}
          </div>

          {/* Terminal demo */}
          <div className="mx-auto mt-10 sm:mt-12 max-w-2xl text-left">
            <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
              <div className="flex items-center gap-2 border-b px-4 py-2.5">
                <span className="size-2.5 rounded-full bg-[oklch(0.65_0.2_25)]" />
                <span className="size-2.5 rounded-full bg-[oklch(0.82_0.16_85)]" />
                <span className="size-2.5 rounded-full bg-[oklch(0.7_0.18_145)]" />
                <span className="ml-2 text-xs font-medium text-muted-foreground">{terminal.title}</span>
              </div>
              <div className="h-[240px] sm:h-[280px] px-4 py-3 font-mono text-[11px] sm:text-xs leading-relaxed overflow-hidden">
                {(() => {
                  let remaining = typed;
                  const rendered: React.ReactNode[] = [];
                  termLines.forEach((line, li) => {
                    if (remaining <= 0) return;
                    const visible = line.text.slice(0, remaining);
                    const isTyping = remaining < line.text.length;
                    remaining -= line.text.length;
                    if (remaining < 0) remaining = 0;

                    const colorCls =
                      line.role === "user"
                        ? "text-foreground/80"
                        : line.role === "tool"
                          ? "text-primary/70"
                          : line.role === "result"
                            ? "text-muted-foreground"
                            : "text-foreground/90";

                    rendered.push(
                      <p key={li} className={`${colorCls} ${line.role === "tool" || line.role === "result" ? "pl-2" : ""} ${line.role === "result" ? "text-[10px] sm:text-[11px]" : ""}`}>
                        {line.role === "user" && <span className="text-primary/60">You</span>}
                        {line.role === "user" && <span className="text-muted-foreground/40"> › </span>}
                        {line.role === "tool" && (
                          <>
                            <span className="text-primary/50">Claude</span>
                            <span className="text-muted-foreground/30"> › </span>
                          </>
                        )}
                        {line.role === "result" && ""}
                        {line.role === "claude" && (
                          <>
                            <span className="text-primary/70">Claude</span>
                            <span className="text-muted-foreground/40"> › </span>
                          </>
                        )}
                        {visible}
                        {isTyping && <span className="animate-pulse text-muted-foreground/40">▎</span>}
                      </p>
                    );
                  });
                  return <div className="space-y-1.5">{rendered}</div>;
                })()}
              </div>
            </div>
          </div>

          {/* Install command */}
          <div className="mx-auto mt-10 sm:mt-12 max-w-lg">
            <button
              onClick={copyInstall}
              className="group flex w-full items-center justify-between gap-3 rounded-lg border bg-muted/50 px-5 py-3 font-mono text-sm transition-colors hover:bg-muted"
            >
              <span className="flex items-center gap-3">
                <span className="text-muted-foreground">$</span>
                <span>uvx oc-piloci install</span>
              </span>
              <span className="text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                {copied ? "✓ 복사됨" : "복사"}
              </span>
            </button>
          </div>

          <div className="mt-8 sm:mt-10">
            <Button size="lg" asChild>
              <Link href="/signup">
                {t.common.signup}
                <ArrowRight className="ml-2 size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t bg-muted py-20">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-12 text-center text-2xl font-bold">{t.landing.sections.features.title}</h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {features.map((f, i) => {
              const Icon = featureIcons[i] ?? Fingerprint;
              return (
                <Card key={f.title}>
                  <CardContent className="p-6">
                    <Icon className="mb-3 size-5 text-primary" />
                    <h3 className="mb-2 font-semibold">{f.title}</h3>
                    <p className="text-sm text-muted-foreground">{f.desc}</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section className="py-20">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-4 text-center text-2xl font-bold">{t.landing.sections.capabilities.title}</h2>
          <p className="mb-12 text-center text-muted-foreground">{t.landing.sections.capabilities.desc}</p>
          <div className="grid gap-6 sm:grid-cols-3">
            {capabilities.map((c, i) => {
              const Icon = toolIcons[i] ?? Database;
              return (
                <Card key={c.name}>
                  <CardContent className="p-6">
                    <Icon className="mb-3 size-5 text-primary" />
                    <h3 className="mb-2 font-mono text-sm font-semibold">{c.name}</h3>
                    <p className="text-sm text-muted-foreground">{c.desc}</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
          <p className="mt-8 text-center text-sm text-muted-foreground/70">{t.landing.sections.capabilities.note}</p>
        </div>
      </section>

      {/* Pricing + Engineering */}
      <section className="border-t bg-muted py-20">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-8 lg:grid-cols-2">
            {/* Free tier card */}
            <Card className="border-primary/20">
              <CardContent className="p-8">
                <Heart className="mb-3 size-5 text-primary" />
                <h2 className="mb-2 text-2xl font-bold">{t.landing.sections.pricing.title}</h2>
                <p className="mb-8 text-sm text-muted-foreground">{t.landing.sections.pricing.desc}</p>
                <ul className="space-y-3">
                  {t.landing.sections.pricing.features.map((f) => (
                    <li key={f} className="flex items-center gap-3 text-sm">
                      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs text-primary">✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            {/* Engineering card */}
            <Card>
              <CardContent className="p-8">
                <Cpu className="mb-3 size-5 text-primary" />
                <h2 className="mb-2 text-2xl font-bold">{t.landing.sections.pricing.engineering.title}</h2>
                <p className="mb-8 text-sm text-muted-foreground">{t.landing.sections.pricing.engineering.desc}</p>
                <dl className="space-y-4">
                  {t.landing.sections.pricing.engineering.items.map((item, i) => {
                    const Icon = engIcons[i] ?? Cpu;
                    return (
                      <div key={item.label} className="flex items-start gap-3">
                        <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10">
                          <Icon className="size-3.5 text-primary" />
                        </div>
                        <div>
                          <dt className="font-mono text-xs font-semibold">{item.label}</dt>
                          <dd className="text-sm text-muted-foreground">{item.desc}</dd>
                        </div>
                      </div>
                    );
                  })}
                </dl>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      <footer className="border-t py-6">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4">
          <p className="text-sm text-muted-foreground">{t.landing.footer}</p>
          <Link href="/privacy" className="text-sm text-muted-foreground/60 hover:text-foreground transition-colors">
            {t.privacy.title}
          </Link>
        </div>
      </footer>
    </div>
  );
}
