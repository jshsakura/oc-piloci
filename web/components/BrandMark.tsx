import Link from "next/link";
import Image from "next/image";

export default function BrandMark({ className }: { className?: string }) {
  return (
    <Link href="/" className={className ?? "inline-flex shrink-0 items-center gap-2 font-semibold tracking-tight"}>
      <Image src="/icon.svg" alt="piLoci" width={24} height={24} className="shrink-0" priority />
      <span
        className="whitespace-nowrap text-base leading-none text-foreground"
        style={{ fontFamily: "var(--font-gugi), sans-serif", letterSpacing: "0.04em" }}
      >
        piLoci
      </span>
    </Link>
  );
}
