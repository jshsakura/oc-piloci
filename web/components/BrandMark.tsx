import Link from "next/link";
import Image from "next/image";

export default function BrandMark({ className }: { className?: string }) {
  return (
    <Link href="/" className={className ?? "inline-flex items-center gap-1.5 font-semibold tracking-tight"}>
      <Image src="/icon.svg" alt="piLoci" width={24} height={24} className="shrink-0" priority />
      <span className="font-[Gugi,sans-serif] text-foreground tracking-wide">piLoci</span>
    </Link>
  );
}
