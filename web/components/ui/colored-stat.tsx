import { cn } from "@/lib/utils";

/**
 * Coloured stat box used in WeeklyDigest, future fun-stats, etc.
 * Picks a category tone so the numbers stay distinguishable in both
 * light and dark themes without leaning on a border.
 *
 *   <ColoredStat label="세션" value={71} tone="blue" />
 */
export type StatTone = "blue" | "rose" | "violet" | "emerald" | "amber";

const TONE_CLASSES: Record<StatTone, string> = {
  blue: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  rose: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  violet: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
  emerald: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  amber: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

export function ColoredStat({
  label,
  value,
  tone,
  className,
}: {
  label: string;
  value: string | number;
  tone: StatTone;
  className?: string;
}) {
  return (
    <div className={cn("rounded-md px-3 py-2", TONE_CLASSES[tone], className)}>
      <p className="text-[10px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}
