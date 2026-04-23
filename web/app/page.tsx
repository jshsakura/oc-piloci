'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/auth';
import { Button } from '@/engine/components/ui/button';
import { GlassCard } from '@/engine/components/ui/glass-card';
import { Aurora } from '@/engine/components/ui/aurora';
import { BrandMark } from '@/components/BrandMark';
import { ThemeToggle } from '@/components/ThemeToggle';
import { useTranslation } from '@/lib/i18n';
import { Locale } from '@/lib/copy';

function useTypewriter(text: string = '', speed = 80, delay = 500) {
  const [displayText, setDisplayText] = useState('');
  const [isStarted, setIsStarted] = useState(false);

  useEffect(() => {
    const timeout = setTimeout(() => setIsStarted(true), delay);
    return () => clearTimeout(timeout);
  }, [delay]);

  useEffect(() => {
    if (!isStarted || !text) return;
    if (displayText.length < text.length) {
      const timeout = setTimeout(() => {
        setDisplayText(text.slice(0, displayText.length + 1));
      }, speed);
      return () => clearTimeout(timeout);
    }
  }, [displayText, text, speed, isStarted]);

  return displayText;
}

export default function LandingPage() {
  const router = useRouter();
  const { user } = useAuthStore();
  const { locale, setLocale, t: copy } = useTranslation();

  // SSR Safe Data Access
  const title1 = copy?.landing?.titleLines?.[0] || '';
  const title2 = copy?.landing?.titleLines?.[1] || '';
  const desc = copy?.landing?.descriptionLines || [];
  const features = copy?.landing?.sections?.features?.list || [];
  const pricing = copy?.landing?.sections?.pricing || { title: '', desc: '', features: [] };

  const typed1 = useTypewriter(title1, 40, 300);
  const typed2 = useTypewriter(title2, 40, title1.length * 40 + 500);

  useEffect(() => {
    if (user) {
      router.replace('/dashboard');
    }
  }, [user, router]);

  if (user) return null;

  return (
    <div className="relative min-h-screen bg-background text-foreground font-sans overflow-x-hidden selection:bg-brand/30" data-skin="linear">
      
      {/* [Engine] Overclocked Visuals */}
      <Aurora className="opacity-90 scale-125" />
      <div className="fixed inset-0 bg-scanline pointer-events-none opacity-20" />

      {/* [Engine] Minimal Floating Header */}
      <header className="fixed top-0 left-0 right-0 z-50 px-6 pt-6 pointer-events-none">
        <div className="mx-auto max-w-7xl flex items-center justify-between pointer-events-auto">
          <div className="reveal-engine">
            <BrandMark iconSize={28} />
          </div>
          
          <div className="flex items-center gap-4 bg-surface-card/60 backdrop-blur-3xl border border-border-mute p-1.5 rounded-full pl-8 shadow-2xl reveal-engine delay-1">
            <nav className="hidden lg:flex items-center gap-8 mr-6 text-[10px] font-black tracking-widest text-text-tertiary uppercase">
              <a href="#features" className="hover:text-brand transition-all">Engine</a>
              <a href="https://github.com" target="_blank" className="hover:text-foreground transition-all underline decoration-brand underline-offset-4 font-black uppercase">Source</a>
            </nav>
            <div className="flex items-center gap-3 border-l border-border-mute pl-6 py-1 pr-1">
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value as Locale)}
                className="bg-transparent text-[11px] font-black text-text-tertiary outline-none cursor-pointer hover:text-brand transition-all uppercase"
              >
                <option value="ko">KO</option>
                <option value="en">EN</option>
              </select>
              <ThemeToggle />
              <Button variant="default" size="xs" asChild className="rounded-full px-6 h-10 font-black shadow-xl shadow-brand/20 border-none">
                <Link href="/login">{copy?.common?.login || 'Init'}</Link>
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-7xl px-6 pt-48 pb-40">
        
        {/* Massive Hero Section */}
        <section className="relative text-center pb-60 border-b border-border/10">
          <div className="mb-14 inline-flex items-center gap-3 rounded-full border border-brand/40 bg-brand-mute px-6 py-2.5 text-[11px] font-black tracking-[0.4em] uppercase text-brand reveal-engine">
            <span className="relative flex h-3 w-3">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-75"></span>
              <span className="relative inline-flex h-3 w-3 rounded-full bg-brand"></span>
            </span>
            {copy?.landing?.badge}
          </div>

          <h1 className="mb-14 text-6xl font-black tracking-[-0.1em] sm:text-[130px] lg:text-[180px] leading-[0.8] text-text-primary uppercase break-all sm:break-normal">
            <span className="block opacity-90">{typed1}</span>
            <span className="block animate-engine-text-vibrant pb-10">
              {typed2}
            </span>
          </h1>

          <div className="mx-auto mb-20 max-w-4xl space-y-6 reveal-engine delay-1">
            {desc.map((line: string, i: number) => (
              <p key={i} className="text-2xl sm:text-4xl font-black tracking-tighter text-text-secondary leading-none uppercase opacity-40 italic">
                {line}
              </p>
            ))}
          </div>

          <div className="flex flex-col items-center gap-14 reveal-engine delay-2">
             <div className="relative group max-w-2xl w-full">
                <div className="absolute -inset-1 bg-gradient-to-r from-neon-purple to-neon-cyan rounded-2xl blur-3xl opacity-20 group-hover:opacity-40 transition duration-700" />
                <div className="relative flex items-center gap-6 bg-black text-white px-8 h-20 rounded-2xl font-mono text-sm sm:text-2xl border border-white/10 shadow-3xl overflow-hidden">
                   <span className="text-neon-purple font-black select-none mr-2">#</span>
                   <span className="font-black uppercase tracking-tight whitespace-nowrap">uvx mcp-piloci install</span>
                   <button className="ml-auto p-3 hover:bg-white/10 rounded-xl transition-all">
                      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                   </button>
                </div>
             </div>
          </div>
        </section>

        {/* [Engine] Bento Grid */}
        <section id="features" className="pb-60 pt-40">
           <div className="grid grid-cols-1 md:grid-cols-12 gap-8 auto-rows-[340px]">
              
              <GlassCard beam className="md:col-span-8 p-14 flex flex-col justify-between border-brand/20 reveal-engine delay-1">
                 <div className="size-16 rounded-2xl bg-brand-mute border border-brand/20 flex items-center justify-center text-brand">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
                 </div>
                 <div>
                    <h3 className="text-5xl font-black tracking-tighter mb-4 uppercase text-foreground">{features[0]?.title}</h3>
                    <p className="max-w-md text-xl text-text-secondary font-bold opacity-70 leading-snug">{features[0]?.desc}</p>
                 </div>
              </GlassCard>

              <GlassCard className="md:col-span-4 p-12 flex flex-col justify-between border-neon-cyan/20 reveal-engine delay-2">
                 <div className="size-14 rounded-2xl bg-neon-cyan/10 border border-neon-cyan/20 flex items-center justify-center text-neon-cyan">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
                 </div>
                 <h3 className="text-3xl font-black tracking-tight uppercase text-foreground leading-none">{features[1]?.title}</h3>
              </GlassCard>

              <GlassCard className="md:col-span-4 p-12 flex flex-col justify-between border-neon-pink/20 reveal-engine delay-3">
                 <div className="size-14 rounded-2xl bg-neon-pink/10 border border-neon-pink/20 flex items-center justify-center text-neon-pink">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                 </div>
                 <h3 className="text-3xl font-black tracking-tight uppercase text-foreground leading-none">{features[2]?.title}</h3>
              </GlassCard>

              {/* [Engine] Fluid Gradient Box User Loved */}
              <div className="md:col-span-8 group relative rounded-[40px] border-none p-[2px] overflow-hidden shadow-2xl animate-engine-gradient-box transition-all hover:scale-[1.005]">
                 <div className="relative z-10 h-full bg-background/90 dark:bg-[#05050a]/95 backdrop-blur-3xl rounded-[38px] p-14 flex flex-col justify-between">
                    <div className="flex justify-between items-start">
                       <div className="size-16 rounded-2xl bg-brand/10 border border-brand/20 flex items-center justify-center text-brand">
                          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                       </div>
                       <div className="text-right">
                          <span className="text-[10px] font-black tracking-widest text-brand uppercase block mb-1 leading-none">Core Version</span>
                          <p className="text-6xl font-black tracking-tighter text-foreground dark:text-white">$0.00</p>
                       </div>
                    </div>
                    <div className="flex flex-col sm:flex-row justify-between items-end gap-10 pt-10">
                       <div className="max-w-md text-left">
                          <h3 className="text-5xl font-black tracking-tighter mb-4 uppercase text-foreground dark:text-white">{pricing.title}</h3>
                          <p className="text-lg font-bold opacity-60 text-foreground dark:text-white leading-tight uppercase italic">{pricing.desc}</p>
                       </div>
                       <Button size="lg" className="rounded-full px-16 h-18 text-xl font-black bg-brand text-white hover:opacity-90 shadow-[0_0_60px_rgba(112,0,255,0.4)] border-none uppercase tracking-widest">Clone Repo</Button>
                    </div>
                 </div>
              </div>
           </div>
        </section>

      </main>

      {/* [Engine] Pure Void Footer */}
      <footer className="py-40 px-6 bg-surface-muted border-t border-border-mute relative z-10">
        <div className="mx-auto max-w-7xl flex flex-col md:flex-row justify-between items-start gap-24">
           <div className="flex flex-wrap gap-24 sm:gap-40 uppercase font-black text-text-tertiary">
              <div className="flex flex-col gap-6">
                <span className="text-[10px] text-brand tracking-[0.5em]">Protocol</span>
                <a href="#" className="text-[16px] hover:text-foreground transition-all opacity-40 hover:opacity-100 tracking-widest font-black">Documentation</a>
                <a href="#" className="text-[16px] hover:text-foreground transition-all opacity-40 hover:opacity-100 tracking-widest font-black">GitHub Repo</a>
              </div>
              <div className="flex flex-col gap-6">
                <span className="text-[10px] text-brand tracking-[0.5em]">Legal</span>
                <a href="#" className="text-[16px] hover:text-foreground transition-all opacity-40 hover:opacity-100 tracking-widest font-black">Privacy Policy</a>
                <a href="#" className="text-[16px] hover:text-foreground transition-all opacity-40 hover:opacity-100 tracking-widest font-black">Terms of Use</a>
              </div>
           </div>
           
           <div className="flex flex-col md:items-end gap-6 w-full md:w-auto">
              <BrandMark iconSize={36} className="grayscale brightness-150 opacity-30 hover:opacity-100 hover:grayscale-0 transition-all" />
              <p className="text-[12px] font-black tracking-[0.3em] uppercase opacity-20">
                {copy?.landing?.footer}
              </p>
           </div>
        </div>
      </footer>
    </div>
  );
}
