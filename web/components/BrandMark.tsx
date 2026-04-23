import Link from 'next/link';
import { getCopy } from '@/lib/copy';

interface BrandMarkProps {
  href?: string;
  className?: string;
  iconSize?: number;
  textClassName?: string;
}

export function BrandMark({
  href = '/',
  className,
  iconSize = 32, // 약간 더 키움
  textClassName,
}: BrandMarkProps) {
  const copy = getCopy();

  return (
    <Link
      href={href}
      className={className}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        textDecoration: 'none',
      }}
    >
      <div style={{ width: iconSize, height: iconSize, flexShrink: 0 }}>
        <svg
          viewBox="0 0 256 256"
          width="100%"
          height="100%"
          style={{ shapeRendering: 'geometricPrecision' }}
        >
          <defs>
            <linearGradient id="pi-logo-grad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="var(--brand, #cba6f7)" />
              <stop offset="100%" stopColor="var(--info, #89b4fa)" />
            </linearGradient>
          </defs>
          
          {/* Background Square with sharp but subtle corners */}
          <rect width="256" height="256" rx="40" fill="currentColor" className="text-surface-subtle" />
          
          {/* High Definition Pi Path - Sharp and solid */}
          <g transform="translate(48, 58) scale(0.65)">
            <path 
              d="M20 30 Q20 0 50 0 H200 Q230 0 230 30 V50 Q230 80 200 80 H50 Q20 80 20 50 Z" 
              fill="url(#pi-logo-grad)" 
            />
            <path 
              d="M60 80 V200 Q60 240 20 240" 
              stroke="url(#pi-logo-grad)" 
              strokeWidth="40" 
              strokeLinecap="square"
              fill="none" 
            />
            <path 
              d="M180 80 V240" 
              stroke="url(#pi-logo-grad)" 
              strokeWidth="40" 
              strokeLinecap="square"
              fill="none" 
            />
          </g>

          {/* Center Activity Dot */}
          <circle cx="128" cy="45" r="10" fill="white" className="animate-pulse" />
        </svg>
      </div>
      <span
        className={textClassName}
        style={{
          fontWeight: 900,
          fontSize: '18px',
          color: 'var(--color-text-primary)',
          letterSpacing: '-0.05em',
          textTransform: 'lowercase',
        }}
      >
        {copy.common.brandName}
      </span>
    </Link>
  );
}
