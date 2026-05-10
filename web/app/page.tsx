"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Fingerprint, Code2, Zap, ShieldCheck, BrainCircuit, Network,
  Lock, Plug, ArrowRight, Activity, TrendingDown, Gauge,
  Database, Search, Brain, Heart, Cpu, HardDrive, Microchip,
  MemoryStick, FileJson, Globe, LayoutDashboard, LogOut, UserCircle,
} from "lucide-react";
import { useAuthStore } from "@/lib/auth";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import BrandMark from "@/components/BrandMark";
import RoutePending from "@/components/RoutePending";
import ThemeToggle from "@/components/ThemeToggle";
import TypingQuotes from "@/components/TypingQuotes";

export default function LandingPage() {
  const { user, hasHydrated, logout } = useAuthStore();
  const { locale, setLocale, t } = useTranslation();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [copiedSetup, setCopiedSetup] = useState(false);
  const [copiedUpdate, setCopiedUpdate] = useState(false);
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
  if ("followUp" in ex && ex.followUp) {
    termLines.push(
      { role: "user", text: ex.followUp.q },
      { role: "tool", text: `⚡ ${ex.followUp.tool}(${ex.followUp.toolArgs})` },
      { role: "result", text: `↳ ${ex.followUp.result}` },
      { role: "claude", text: ex.followUp.a },
    );
  }

  const totalChars = termLines.reduce((s, l) => s + l.text.length, 0);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (typed < totalChars) {
      termTimer.current = setTimeout(() => setTyped((c) => c + 1), 22);
    } else {
      termTimer.current = setTimeout(() => {
        setTermIdx((i) => (i + 1) % terminal.examples.length);
        setTyped(0);
      }, "followUp" in ex && ex.followUp ? 3800 : 2800);
    }
    return () => { if (termTimer.current) clearTimeout(termTimer.current); };
  }, [typed, totalChars, terminal.examples.length, ex]);

  const copySetup = () => {
    navigator.clipboard.writeText("uvx oc-piloci setup");
    setCopiedSetup(true);
    setTimeout(() => setCopiedSetup(false), 2000);
  };

  const copyUpdate = () => {
    navigator.clipboard.writeText("uvx oc-piloci@latest setup");
    setCopiedUpdate(true);
    setTimeout(() => setCopiedUpdate(false), 2000);
  };

  if (!mounted || !hasHydrated) {
    return (
      <RoutePending
        fullScreen
        title={t.landing.pending.title}
        description={t.landing.pending.desc}
      />
    );
  }

  const features = t.landing.sections.features.list;
  const capabilities = t.landing.sections.capabilities.list;
  const curation = t.landing.sections.curation;
  const stats = t.landing.stats;

  const featureIcons = [Fingerprint, Code2, Zap, ShieldCheck, BrainCircuit, Network, Lock, Plug];
  const toolIcons = [Database, Search, Brain];
  const engIcons = [Database, HardDrive, Microchip, MemoryStick, FileJson, Globe];

  return (
    <div className="pi-app-bg bg-background">
      {/* Nav */}
      <header className="pi-glass-nav sticky top-0 z-50 border-b backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <BrandMark />
            <span className="flex items-center gap-1.5 rounded-full border border-green-300 bg-green-50 px-2 py-0.5 text-[10px] font-semibold text-green-700 tracking-wide dark:border-green-400/50 dark:bg-green-500/10 dark:text-green-400">
              <span className="relative flex size-1.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-green-500/75 dark:bg-green-400/75" />
                <span className="relative inline-flex size-1.5 rounded-full bg-green-600 dark:bg-green-400" />
              </span>
              {t.common.badge}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {user ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="flex size-8 cursor-pointer items-center justify-center rounded-full border bg-background/60 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <UserCircle className="size-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <div className="px-2 py-1.5 text-xs text-muted-foreground select-none">{user.email}</div>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link href="/dashboard">
                      <LayoutDashboard className="me-2 size-4" />
                      {t.appShell.nav.dashboard}
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={async () => { await api.logout().catch(() => {}); logout(); router.push("/login"); }}
                    className="text-destructive"
                  >
                    <LogOut className="me-2 size-4" />
                    {t.appShell.dropdown.logout}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <button
                type="button"
                onClick={() => router.push("/login")}
                className="flex size-8 cursor-pointer items-center justify-center rounded-full border bg-background/60 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <UserCircle className="size-4" />
              </button>
            )}
            <button
              onClick={() => setLocale(locale === "ko" ? "en" : "ko")}
              className="flex h-8 cursor-pointer items-center gap-1 rounded-md border border-border px-2 text-xs font-medium text-muted-foreground shadow-sm transition-colors hover:bg-muted hover:text-foreground"
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
            <div className="pi-panel overflow-hidden rounded-xl">
              <div className="flex items-center gap-2 border-b px-4 py-2.5">
                <span className="size-2.5 rounded-full bg-[oklch(0.65_0.2_25)]" />
                <span className="size-2.5 rounded-full bg-[oklch(0.82_0.16_85)]" />
                <span className="size-2.5 rounded-full bg-[oklch(0.7_0.18_145)]" />
                <span className="ms-2 text-xs font-medium text-muted-foreground">{terminal.title}</span>
              </div>
              <div className="px-4 py-3 font-mono text-[11px] sm:text-xs leading-relaxed overflow-hidden h-[260px] sm:h-[300px]">
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
                        {isTyping && <span className="text-foreground/70" style={{ animation: 'blink 1s step-end infinite' }}>│</span>}
                      </p>
                    );
                  });
                  return <div className="space-y-1.5">{rendered}</div>;
                })()}
              </div>
            </div>
          </div>

          {/* Install */}
          <div className="mx-auto mt-10 sm:mt-12 max-w-2xl space-y-3">
            {/* uv 선행 설치 */}
            <div className="rounded-xl border border-dashed bg-muted/30 p-4">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-bold text-muted-foreground">1</span>
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                    {t.landing.sections.install.uvEyebrow}
                  </p>
                  <button
                    onClick={() => { navigator.clipboard.writeText("curl -LsSf https://astral.sh/uv/install.sh | sh"); }}
                    className="group flex w-full items-center justify-between gap-2 rounded-lg border bg-muted/50 px-4 py-2 font-mono text-xs transition-colors hover:bg-muted cursor-pointer"
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <span className="text-muted-foreground">$</span>
                      <span className="truncate">curl -LsSf https://astral.sh/uv/install.sh | sh</span>
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">{t.common.copy}</span>
                  </button>
                </div>
              </div>
            </div>

            {/* 설치 + 업데이트 */}
            <div className="grid gap-4 sm:grid-cols-2">
              {/* 설치 */}
              <div className="space-y-3 rounded-xl border bg-card p-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary">
                  {t.landing.sections.install.eyebrow}
                </p>
                <button
                  onClick={copySetup}
                  className="group flex w-full items-center justify-between gap-2 rounded-lg border bg-muted/50 px-4 py-2.5 font-mono text-sm transition-colors hover:bg-muted cursor-pointer"
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="text-muted-foreground">$</span>
                    <span className="truncate">uvx oc-piloci setup</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                    {copiedSetup ? t.common.copied : t.common.copy}
                  </span>
                </button>
                <div className="flex flex-wrap gap-1">
                  {t.landing.sections.install.platforms.map((p) => (
                    <span
                      key={p.name}
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                        p.status === "auto"
                          ? "border-primary/20 bg-primary/5 text-foreground/70"
                          : "border-border text-muted-foreground/50"
                      }`}
                    >
                      <span className={`size-1.5 rounded-full ${p.status === "auto" ? "bg-primary/60" : "bg-muted-foreground/30"}`} />
                      {p.name}
                    </span>
                  ))}
                </div>
              </div>

              {/* 업데이트 */}
              <div className="space-y-3 rounded-xl border bg-card p-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary">
                  {t.landing.sections.install.updateEyebrow}
                </p>
                <button
                  onClick={copyUpdate}
                  className="group flex w-full items-center justify-between gap-2 rounded-lg border bg-muted/50 px-4 py-2.5 font-mono text-sm transition-colors hover:bg-muted cursor-pointer"
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="text-muted-foreground">$</span>
                    <span className="truncate">uvx oc-piloci@latest setup</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                    {copiedUpdate ? t.common.copied : t.common.copy}
                  </span>
                </button>
              </div>
            </div>

            {/* 삭제 안내 */}
            <p className="text-center text-xs text-muted-foreground/60">
              {t.landing.sections.install.uninstallNote}
            </p>
          </div>

          <div className="mt-8 sm:mt-10">
            <Button size="lg" asChild>
              <Link href={user ? "/dashboard" : "/signup"}>
                {user ? t.appShell.nav.dashboard : t.common.signup}
                <ArrowRight className="ms-2 size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="border-t bg-muted section-pattern py-20">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-3 text-center text-2xl font-bold">{t.landing.sections.features.title}</h2>
          <div className="mx-auto mb-12 max-w-3xl space-y-3 text-center text-muted-foreground">
            {t.landing.sections.features.subtitle.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
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

      {/* Quiet curator */}
      <section className="border-t py-20">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.28em] text-primary">
              {curation.eyebrow}
            </p>
            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              {curation.title}
            </h2>
            <div className="mt-6 space-y-4 text-muted-foreground">
              {curation.paragraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              {curation.stages.map((stage, index) => (
                <div key={stage.label} className="rounded-xl border bg-card p-4">
                  <p className="mb-3 flex size-7 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                    {index + 1}
                  </p>
                  <h3 className="font-semibold">{stage.label}</h3>
                  <p className="mt-2 text-sm text-muted-foreground">{stage.desc}</p>
                </div>
              ))}
            </div>
          </div>

          <Card className="overflow-hidden border-primary/20 bg-card/80 shadow-[0_24px_80px_rgba(15,23,42,0.08)]">
            <CardContent className="p-6 sm:p-8">
              <div className="mb-6 flex items-start justify-between gap-4">
                <div>
                  <div className="mb-3 flex size-10 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                    <Network className="size-5" />
                  </div>
                  <h3 className="text-xl font-bold">{curation.graphTitle}</h3>
                  <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    {curation.graphDesc}
                  </p>
                </div>
              </div>

              <div className="relative min-h-[220px] overflow-hidden rounded-2xl sm:rounded-3xl border bg-muted/40 sm:aspect-[4/3]">
                <div
                  className="absolute inset-0 opacity-[0.035]"
                  style={{
                    backgroundImage: "radial-gradient(circle, currentColor 1px, transparent 1px)",
                    backgroundSize: "20px 20px",
                  }}
                />

                <svg
                  className="absolute inset-0 h-full w-full"
                  viewBox="0 0 100 75"
                  preserveAspectRatio="none"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <circle cx="50" cy="37.5" r="16" className="fill-primary/[0.04]" />
                  <circle cx="50" cy="37.5" r="9" className="fill-primary/[0.07]" />
                  <path d="M 16 14 Q 30 24 50 37.5" stroke="currentColor" strokeWidth="0.2" className="text-primary/20" strokeDasharray="1 1.5" />
                  <circle cx="16" cy="14" r="0.9" className="fill-primary/30" />
                  <path d="M 84 14 Q 68 24 50 37.5" stroke="currentColor" strokeWidth="0.2" className="text-primary/20" strokeDasharray="1 1.5" />
                  <circle cx="84" cy="14" r="0.9" className="fill-primary/30" />
                  <path d="M 16 62 Q 30 52 50 37.5" stroke="currentColor" strokeWidth="0.2" className="text-primary/20" strokeDasharray="1 1.5" />
                  <circle cx="16" cy="62" r="0.9" className="fill-primary/30" />
                  <path d="M 84 62 Q 68 52 50 37.5" stroke="currentColor" strokeWidth="0.2" className="text-primary/20" strokeDasharray="1 1.5" />
                  <circle cx="84" cy="62" r="0.9" className="fill-primary/30" />
                </svg>

                {/* Project — top-left */}
                <div className="absolute left-[5%] top-[5%] rounded-lg sm:rounded-xl border bg-background/95 px-2 py-1 sm:px-3 sm:py-2 shadow-sm backdrop-blur-sm">
                  <p className="text-[8px] sm:text-[10px] font-semibold uppercase tracking-wider text-primary">{curation.graphNodes.project.label}</p>
                  <p className="text-xs sm:text-sm font-medium">{curation.graphNodes.project.value}</p>
                </div>
                {/* Decision — top-right */}
                <div className="absolute right-[5%] top-[5%] rounded-lg sm:rounded-xl border bg-background/95 px-2 py-1 sm:px-3 sm:py-2 shadow-sm backdrop-blur-sm">
                  <p className="text-[8px] sm:text-[10px] font-semibold uppercase tracking-wider text-primary">{curation.graphNodes.decision.label}</p>
                  <p className="text-xs sm:text-sm font-medium">{curation.graphNodes.decision.value}</p>
                </div>
                {/* Curated — center hub */}
                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-xl sm:rounded-2xl border border-primary/30 bg-primary px-3 py-2 sm:px-5 sm:py-4 text-primary-foreground shadow-lg">
                  <p className="text-[8px] sm:text-[10px] font-semibold uppercase tracking-wider opacity-80">{curation.graphNodes.curated.label}</p>
                  <p className="text-xs sm:text-sm font-semibold">{curation.graphNodes.curated.value}</p>
                </div>
                {/* Constraint — bottom-left */}
                <div className="absolute left-[5%] bottom-[5%] rounded-lg sm:rounded-xl border bg-background/95 px-2 py-1 sm:px-3 sm:py-2 shadow-sm backdrop-blur-sm">
                  <p className="text-[8px] sm:text-[10px] font-semibold uppercase tracking-wider text-primary">{curation.graphNodes.constraint.label}</p>
                  <p className="text-xs sm:text-sm font-medium">{curation.graphNodes.constraint.value}</p>
                </div>
                {/* Preference — bottom-right */}
                <div className="absolute right-[5%] bottom-[5%] rounded-lg sm:rounded-xl border bg-background/95 px-2 py-1 sm:px-3 sm:py-2 shadow-sm backdrop-blur-sm">
                  <p className="text-[8px] sm:text-[10px] font-semibold uppercase tracking-wider text-primary">{curation.graphNodes.preference.label}</p>
                  <p className="text-xs sm:text-sm font-medium">{curation.graphNodes.preference.value}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Capabilities */}
      <section className="bg-muted section-pattern py-20">
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
        </div>
      </section>

      {/* Pricing + Engineering */}
      <section className="border-t py-20">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-8 lg:grid-cols-2">
            {/* Free tier card */}
            <Card className="border-primary/20">
              <CardContent className="p-8">
                <Heart className="mb-3 size-5 text-primary" />
                <h2 className="mb-2 text-2xl font-bold">{t.landing.sections.pricing.title}</h2>
                <div className="mb-8 space-y-1">
                  {t.landing.sections.pricing.desc.map((line, i) => (
                    <p key={i} className="text-sm text-muted-foreground">{line}</p>
                  ))}
                </div>
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

      <footer className="border-t bg-background py-6">
        <div className="mx-auto flex flex-col items-center gap-3 sm:flex-row sm:justify-between max-w-6xl px-4">
          <p className="text-sm text-muted-foreground">{t.landing.footer}</p>
          <div className="flex items-center gap-4">
            <Link href="/privacy" className="text-sm text-muted-foreground/60 hover:text-foreground transition-colors">
              {t.privacy.title}
            </Link>
            <Link href="/terms" className="text-sm text-muted-foreground/60 hover:text-foreground transition-colors">
              {t.terms.title}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
