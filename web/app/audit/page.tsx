'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/lib/auth';
import { NavBar } from '@/components/NavBar';
import { Badge } from '@/engine/components/ui/badge';
import { Button } from '@/engine/components/ui/button';
import { Skeleton } from '@/engine/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/engine/components/ui/select';

const LIMIT = 50;

const ACTION_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'login_success', label: 'login_success' },
  { value: 'login_fail', label: 'login_fail' },
  { value: 'signup', label: 'signup' },
  { value: 'token_created', label: 'token_created' },
  { value: 'token_revoked', label: 'token_revoked' },
  { value: 'project_created', label: 'project_created' },
  { value: 'project_deleted', label: 'project_deleted' },
];

interface AuditLog {
  id: number;
  action: string;
  ip_address: string | null;
  user_agent: string | null;
  meta_data: string | null;
  created_at: string;
}

function formatKST(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleString('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return isoString;
  }
}

function shortUA(ua: string | null): string {
  if (!ua) return '-';
  // Extract browser name
  const match =
    ua.match(/\b(Chrome|Firefox|Safari|Edge|OPR|Opera|Brave)\/[\d.]+/i) ||
    ua.match(/\b(curl|python-requests|axios|okhttp)\b/i);
  if (match) return match[0].slice(0, 32);
  return ua.slice(0, 32) + (ua.length > 32 ? '…' : '');
}

function ActionBadge({ action }: { action: string }) {
  if (action === 'login_success') {
    return (
      <Badge
        style={{
          backgroundColor: 'rgba(34,197,94,0.15)',
          color: '#22C55E',
          borderColor: 'rgba(34,197,94,0.3)',
        }}
      >
        {action}
      </Badge>
    );
  }
  if (action === 'login_fail') {
    return (
      <Badge
        style={{
          backgroundColor: 'rgba(239,68,68,0.15)',
          color: '#EF4444',
          borderColor: 'rgba(239,68,68,0.3)',
        }}
      >
        {action}
      </Badge>
    );
  }
  return <Badge variant="outline">{action}</Badge>;
}

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i}>
          <td style={{ padding: '12px 16px' }}>
            <Skeleton className="h-4 w-36" />
          </td>
          <td style={{ padding: '12px 16px' }}>
            <Skeleton className="h-5 w-24 rounded-full" />
          </td>
          <td style={{ padding: '12px 16px' }}>
            <Skeleton className="h-4 w-28" />
          </td>
          <td style={{ padding: '12px 16px' }}>
            <Skeleton className="h-4 w-40" />
          </td>
        </tr>
      ))}
    </>
  );
}

export default function AuditPage() {
  const router = useRouter();
  const { user } = useAuthStore();

  const [actionFilter, setActionFilter] = useState('');
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (user === null) {
      router.replace('/login');
    }
  }, [user, router]);

  if (user === null) {
    return null;
  }

  const queryKey = ['audit', actionFilter, offset];

  const { data: logs, isLoading, isError } = useQuery<AuditLog[]>({
    queryKey,
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(LIMIT),
        offset: String(offset),
      });
      if (actionFilter) params.set('action', actionFilter);
      const res = await fetch(`/api/audit?${params}`, { credentials: 'include' });
      if (!res.ok) throw new Error('Failed to fetch audit logs');
      return res.json();
    },
    enabled: !!user,
  });

  const handleActionChange = (value: string) => {
    setActionFilter(value);
    setOffset(0);
  };

  const hasPrev = offset > 0;
  const hasNext = (logs?.length ?? 0) === LIMIT;

  const sectionCardStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-surface-raised, #1A1A1F)',
    border: '1px solid var(--color-border, #2A2A35)',
    borderRadius: '14px',
    overflow: 'hidden',
  };

  const thStyle: React.CSSProperties = {
    padding: '10px 16px',
    textAlign: 'left',
    fontSize: '11px',
    fontWeight: 600,
    color: '#9494A0',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    borderBottom: '1px solid #2A2A35',
    backgroundColor: 'rgba(255,255,255,0.02)',
    whiteSpace: 'nowrap',
  };

  const tdStyle: React.CSSProperties = {
    padding: '12px 16px',
    fontSize: '13px',
    color: '#E8E8ED',
    borderBottom: '1px solid rgba(42,42,53,0.6)',
    verticalAlign: 'middle',
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--color-surface-page, #0F0F10)',
        color: 'var(--color-text-primary, #E8E8ED)',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
      data-skin="linear"
    >
      <NavBar title="감사 로그" />

      <main style={{ maxWidth: '960px', margin: '0 auto', padding: '32px 24px 80px' }}>
        {/* Back link */}
        <div style={{ marginBottom: '24px' }}>
          <Link
            href="/settings"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '13px',
              color: '#9494A0',
              textDecoration: 'none',
              transition: 'color 0.15s',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.color = '#E8E8ED';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.color = '#9494A0';
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
            설정
          </Link>
        </div>

        {/* Page title + filter */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
            marginBottom: '24px',
          }}
        >
          <h1
            style={{
              fontSize: '26px',
              fontWeight: 800,
              letterSpacing: '-0.02em',
              color: '#E8E8ED',
              margin: 0,
            }}
          >
            감사 로그
          </h1>

          <div style={{ minWidth: '180px' }}>
            <Select value={actionFilter} onValueChange={handleActionChange}>
              <SelectTrigger size="sm">
                <SelectValue placeholder="액션 필터" />
              </SelectTrigger>
              <SelectContent>
                {ACTION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Table card */}
        <div style={sectionCardStyle}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={thStyle}>시각 (KST)</th>
                  <th style={thStyle}>액션</th>
                  <th style={thStyle}>IP</th>
                  <th style={thStyle}>브라우저</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <SkeletonRows />
                ) : isError ? (
                  <tr>
                    <td colSpan={4} style={{ ...tdStyle, textAlign: 'center', color: '#EF4444', padding: '32px' }}>
                      데이터를 불러오지 못했습니다.
                    </td>
                  </tr>
                ) : !logs || logs.length === 0 ? (
                  <tr>
                    <td
                      colSpan={4}
                      style={{
                        ...tdStyle,
                        textAlign: 'center',
                        color: '#9494A0',
                        padding: '48px 16px',
                      }}
                    >
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                        <svg
                          width="32"
                          height="32"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="#2A2A35"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                          <line x1="16" y1="13" x2="8" y2="13" />
                          <line x1="16" y1="17" x2="8" y2="17" />
                          <polyline points="10 9 9 9 8 9" />
                        </svg>
                        <span style={{ fontSize: '14px' }}>감사 로그가 없습니다</span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  logs.map((log) => (
                    <tr
                      key={log.id}
                      style={{ transition: 'background-color 0.1s' }}
                      onMouseEnter={(e) => {
                        (e.currentTarget as HTMLTableRowElement).style.backgroundColor =
                          'rgba(255,255,255,0.025)';
                      }}
                      onMouseLeave={(e) => {
                        (e.currentTarget as HTMLTableRowElement).style.backgroundColor = 'transparent';
                      }}
                    >
                      <td style={{ ...tdStyle, color: '#9494A0', fontFamily: 'monospace', fontSize: '12px' }}>
                        {formatKST(log.created_at)}
                      </td>
                      <td style={tdStyle}>
                        <ActionBadge action={log.action} />
                      </td>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: '12px', color: '#9494A0' }}>
                        {log.ip_address ?? '-'}
                      </td>
                      <td style={{ ...tdStyle, color: '#9494A0', fontSize: '12px' }}>
                        {shortUA(log.user_agent)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {!isLoading && !isError && (hasPrev || hasNext) && (
            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 16px',
                borderTop: '1px solid #2A2A35',
              }}
            >
              <Button
                variant="outline"
                size="sm"
                disabled={!hasPrev}
                onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
              >
                이전
              </Button>
              <span style={{ fontSize: '12px', color: '#9494A0' }}>
                {offset / LIMIT + 1} 페이지
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasNext}
                onClick={() => setOffset((o) => o + LIMIT)}
              >
                다음
              </Button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
