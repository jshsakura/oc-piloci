'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/auth';
import { NavBar } from '@/components/NavBar';
import { TokenManager } from '@/components/TokenManager';
import { api } from '@/lib/api';

const MCP_EXAMPLE = `{
  "mcpServers": {
    "piloci": {
      "type": "http",
      "url": "https://piloci.jshsakura.com/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}`;

export default function SettingsPage() {
  const router = useRouter();
  const { user } = useAuthStore();

  // Password change form state (UI only)
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwError, setPwError] = useState('');
  const [pwSuccess, setPwSuccess] = useState(false);

  const [copiedMcp, setCopiedMcp] = useState(false);

  // 2FA state
  const [totpEnabled, setTotpEnabled] = useState(false);
  const [totpStep, setTotpStep] = useState<'idle' | 'setup' | 'backup'>('idle');
  const [totpQr, setTotpQr] = useState('');
  const [totpSecret, setTotpSecret] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [totpError, setTotpError] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [disablePassword, setDisablePassword] = useState('');
  const [disableCode, setDisableCode] = useState('');
  const [disableError, setDisableError] = useState('');
  const [showDisableForm, setShowDisableForm] = useState(false);

  useEffect(() => {
    if (!user) {
      router.replace('/login');
    } else {
      setTotpEnabled(!!(user as { totp_enabled?: boolean }).totp_enabled);
    }
  }, [user, router]);

  if (!user) return null;

  const handle2faEnable = async () => {
    setTotpError('');
    try {
      const data = await api.enable2fa();
      setTotpQr(data.qr);
      setTotpSecret(data.secret);
      setTotpStep('setup');
    } catch (e: unknown) {
      setTotpError((e as Error).message || '2FA 설정 실패');
    }
  };

  const handle2faConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setTotpError('');
    try {
      const data = await api.confirm2fa(totpCode);
      setBackupCodes(data.backup_codes);
      setTotpEnabled(true);
      setTotpStep('backup');
      setTotpCode('');
    } catch (e: unknown) {
      setTotpError((e as Error).message || '코드 확인 실패');
    }
  };

  const handle2faDisable = async (e: React.FormEvent) => {
    e.preventDefault();
    setDisableError('');
    try {
      await api.disable2fa(disablePassword, disableCode);
      setTotpEnabled(false);
      setShowDisableForm(false);
      setDisablePassword('');
      setDisableCode('');
    } catch (e: unknown) {
      setDisableError((e as Error).message || '비활성화 실패');
    }
  };

  const handlePasswordChange = (e: React.FormEvent) => {
    e.preventDefault();
    setPwError('');
    setPwSuccess(false);
    if (!currentPw || !newPw || !confirmPw) {
      setPwError('모든 필드를 입력해주세요.');
      return;
    }
    if (newPw !== confirmPw) {
      setPwError('새 비밀번호가 일치하지 않습니다.');
      return;
    }
    if (newPw.length < 8) {
      setPwError('비밀번호는 최소 8자 이상이어야 합니다.');
      return;
    }
    // TODO: API 연결 필요
    setPwSuccess(true);
    setCurrentPw('');
    setNewPw('');
    setConfirmPw('');
  };

  const handleCopyMcp = async () => {
    try {
      await navigator.clipboard.writeText(MCP_EXAMPLE);
      setCopiedMcp(true);
      setTimeout(() => setCopiedMcp(false), 2000);
    } catch {
      // clipboard not available
    }
  };

  // ── Styles ──────────────────────────────────────────────────────────
  const sectionCardStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-surface-raised, #1A1A1F)',
    border: '1px solid var(--color-border, #2A2A35)',
    borderRadius: '14px',
    padding: '28px',
  };

  const sectionTitleStyle: React.CSSProperties = {
    fontSize: '16px',
    fontWeight: 700,
    color: '#E8E8ED',
    marginBottom: '20px',
    marginTop: 0,
    letterSpacing: '-0.01em',
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '9px 12px',
    borderRadius: '8px',
    border: '1px solid var(--color-border, #2A2A35)',
    backgroundColor: '#0F0F10',
    color: 'var(--color-text-primary, #E8E8ED)',
    fontSize: '14px',
    outline: 'none',
    boxSizing: 'border-box',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: '12px',
    fontWeight: 500,
    color: '#9494A0',
    marginBottom: '6px',
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
      <NavBar title="설정" />

      <main style={{ maxWidth: '760px', margin: '0 auto', padding: '32px 24px 80px' }}>
        {/* Back link */}
        <div style={{ marginBottom: '24px' }}>
          <Link
            href="/dashboard"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '13px',
              color: '#9494A0',
              textDecoration: 'none',
              transition: 'color 0.15s',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#E8E8ED'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#9494A0'; }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            대시보드
          </Link>
        </div>

        {/* Page title */}
        <h1
          style={{
            fontSize: '26px',
            fontWeight: 800,
            letterSpacing: '-0.02em',
            color: '#E8E8ED',
            marginBottom: '32px',
            marginTop: 0,
          }}
        >
          설정
        </h1>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

          {/* ── Section 1: 계정 정보 ──────────────────────────────── */}
          <section style={sectionCardStyle}>
            <h2 style={sectionTitleStyle}>계정 정보</h2>

            {/* Email display */}
            <div style={{ marginBottom: '24px' }}>
              <span style={labelStyle}>이메일</span>
              <div
                style={{
                  padding: '9px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--color-border, #2A2A35)',
                  backgroundColor: 'rgba(255,255,255,0.03)',
                  fontSize: '14px',
                  color: '#E8E8ED',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9494A0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
                {user.email}
              </div>
            </div>

            {/* Divider */}
            <div style={{ borderTop: '1px solid #2A2A35', marginBottom: '24px' }} />

            {/* Password change form */}
            <h3
              style={{
                fontSize: '14px',
                fontWeight: 600,
                color: '#E8E8ED',
                marginBottom: '16px',
                marginTop: 0,
              }}
            >
              비밀번호 변경
            </h3>
            <form onSubmit={handlePasswordChange}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div>
                  <label style={labelStyle}>현재 비밀번호</label>
                  <input
                    type="password"
                    value={currentPw}
                    onChange={(e) => setCurrentPw(e.target.value)}
                    autoComplete="current-password"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>새 비밀번호</label>
                  <input
                    type="password"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    autoComplete="new-password"
                    style={inputStyle}
                  />
                </div>
                <div>
                  <label style={labelStyle}>새 비밀번호 확인</label>
                  <input
                    type="password"
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    autoComplete="new-password"
                    style={inputStyle}
                  />
                </div>

                {pwError && (
                  <p style={{ fontSize: '13px', color: '#EF4444', margin: 0 }}>{pwError}</p>
                )}
                {pwSuccess && (
                  <p style={{ fontSize: '13px', color: '#22C55E', margin: 0 }}>
                    비밀번호가 변경되었습니다.
                  </p>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    type="submit"
                    style={{
                      padding: '8px 18px',
                      borderRadius: '8px',
                      border: 'none',
                      backgroundColor: '#4B32C3',
                      color: '#fff',
                      fontSize: '14px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    변경
                  </button>
                </div>
              </div>
            </form>
          </section>

          {/* ── Section 2: API 토큰 관리 ─────────────────────────── */}
          <section style={sectionCardStyle}>
            <h2 style={sectionTitleStyle}>API 토큰 관리</h2>
            <TokenManager />
          </section>

          {/* ── Section: 2단계 인증 ──────────────────────────────── */}
          <section style={sectionCardStyle}>
            <h2 style={sectionTitleStyle}>2단계 인증 (2FA)</h2>

            {/* Status badge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '4px 10px',
                  borderRadius: '20px',
                  fontSize: '12px',
                  fontWeight: 600,
                  backgroundColor: totpEnabled ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                  color: totpEnabled ? '#22C55E' : '#EF4444',
                  border: `1px solid ${totpEnabled ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                }}
              >
                <div style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: 'currentColor' }} />
                {totpEnabled ? '활성화됨' : '비활성화됨'}
              </div>
            </div>

            {/* Setup flow: step=idle → setup → backup */}
            {totpStep === 'idle' && !totpEnabled && (
              <div>
                <p style={{ fontSize: '14px', color: '#9494A0', marginBottom: '16px', marginTop: 0, lineHeight: 1.6 }}>
                  Google Authenticator 등 TOTP 앱으로 2단계 인증을 설정하면 계정 보안이 강화됩니다.
                </p>
                <button
                  onClick={handle2faEnable}
                  style={{
                    padding: '8px 18px',
                    borderRadius: '8px',
                    border: 'none',
                    backgroundColor: '#4B32C3',
                    color: '#fff',
                    fontSize: '14px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  2FA 설정 시작
                </button>
                {totpError && <p style={{ fontSize: '13px', color: '#EF4444', marginTop: '10px', marginBottom: 0 }}>{totpError}</p>}
              </div>
            )}

            {totpStep === 'setup' && (
              <div>
                <p style={{ fontSize: '14px', color: '#9494A0', marginBottom: '16px', marginTop: 0, lineHeight: 1.6 }}>
                  1. Authenticator 앱으로 QR 코드를 스캔하세요.<br />
                  2. 앱에 표시된 6자리 코드를 입력하고 확인하세요.
                </p>
                {totpQr && (
                  <div style={{ marginBottom: '20px' }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={totpQr} alt="TOTP QR code" style={{ width: 180, height: 180, borderRadius: '8px', border: '1px solid #2A2A35' }} />
                    <p style={{ fontSize: '12px', color: '#9494A0', marginTop: '8px', marginBottom: 0 }}>
                      QR 스캔 불가 시 수동 입력:&nbsp;
                      <code style={{ fontFamily: 'monospace', backgroundColor: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px', fontSize: '12px', color: '#E8E8ED' }}>
                        {totpSecret}
                      </code>
                    </p>
                  </div>
                )}
                <form onSubmit={handle2faConfirm} style={{ display: 'flex', gap: '10px', alignItems: 'flex-end' }}>
                  <div style={{ flex: 1 }}>
                    <label style={{ ...{ display: 'block', fontSize: '12px', fontWeight: 500, color: '#9494A0', marginBottom: '6px' } }}>인증 코드 (6자리)</label>
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      value={totpCode}
                      onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="123456"
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid #2A2A35', backgroundColor: '#0F0F10', color: '#E8E8ED', fontSize: '14px', outline: 'none', boxSizing: 'border-box', fontFamily: 'monospace', letterSpacing: '0.1em' }}
                    />
                  </div>
                  <button
                    type="submit"
                    style={{ padding: '9px 18px', borderRadius: '8px', border: 'none', backgroundColor: '#4B32C3', color: '#fff', fontSize: '14px', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' }}
                  >
                    확인
                  </button>
                </form>
                {totpError && <p style={{ fontSize: '13px', color: '#EF4444', marginTop: '10px', marginBottom: 0 }}>{totpError}</p>}
              </div>
            )}

            {totpStep === 'backup' && backupCodes.length > 0 && (
              <div>
                <div
                  style={{
                    display: 'flex',
                    gap: '8px',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    backgroundColor: 'rgba(234,179,8,0.08)',
                    border: '1px solid rgba(234,179,8,0.25)',
                    marginBottom: '16px',
                  }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#EAB308" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                    <line x1="12" y1="9" x2="12" y2="13" />
                    <line x1="12" y1="17" x2="12.01" y2="17" />
                  </svg>
                  <p style={{ fontSize: '13px', color: '#EAB308', margin: 0, lineHeight: 1.6 }}>
                    <strong>백업 코드를 지금 안전한 곳에 저장하세요.</strong> 이 화면을 닫으면 다시 볼 수 없습니다.
                  </p>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '6px',
                    padding: '16px',
                    borderRadius: '8px',
                    backgroundColor: '#0F0F10',
                    border: '1px solid #2A2A35',
                    marginBottom: '16px',
                    fontFamily: 'monospace',
                  }}
                >
                  {backupCodes.map((code, i) => (
                    <span key={i} style={{ fontSize: '13px', color: '#E8E8ED', padding: '2px 0' }}>{code}</span>
                  ))}
                </div>
                <button
                  onClick={() => setTotpStep('idle')}
                  style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', backgroundColor: '#22C55E', color: '#fff', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }}
                >
                  완료
                </button>
              </div>
            )}

            {totpStep === 'idle' && totpEnabled && (
              <div>
                {!showDisableForm ? (
                  <button
                    onClick={() => setShowDisableForm(true)}
                    style={{ padding: '8px 18px', borderRadius: '8px', border: '1px solid rgba(239,68,68,0.4)', backgroundColor: 'transparent', color: '#EF4444', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }}
                  >
                    2FA 비활성화
                  </button>
                ) : (
                  <form onSubmit={handle2faDisable}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: '#9494A0', marginBottom: '6px' }}>현재 비밀번호</label>
                        <input
                          type="password"
                          value={disablePassword}
                          onChange={(e) => setDisablePassword(e.target.value)}
                          style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid #2A2A35', backgroundColor: '#0F0F10', color: '#E8E8ED', fontSize: '14px', outline: 'none', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: '#9494A0', marginBottom: '6px' }}>TOTP 코드</label>
                        <input
                          type="text"
                          inputMode="numeric"
                          maxLength={6}
                          value={disableCode}
                          onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, ''))}
                          placeholder="123456"
                          style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', border: '1px solid #2A2A35', backgroundColor: '#0F0F10', color: '#E8E8ED', fontSize: '14px', outline: 'none', boxSizing: 'border-box', fontFamily: 'monospace' }}
                        />
                      </div>
                      {disableError && <p style={{ fontSize: '13px', color: '#EF4444', margin: 0 }}>{disableError}</p>}
                      <div style={{ display: 'flex', gap: '10px' }}>
                        <button type="submit" style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', backgroundColor: '#EF4444', color: '#fff', fontSize: '14px', fontWeight: 600, cursor: 'pointer' }}>
                          비활성화
                        </button>
                        <button
                          type="button"
                          onClick={() => { setShowDisableForm(false); setDisableError(''); }}
                          style={{ padding: '8px 18px', borderRadius: '8px', border: '1px solid #2A2A35', backgroundColor: 'transparent', color: '#9494A0', fontSize: '14px', cursor: 'pointer' }}
                        >
                          취소
                        </button>
                      </div>
                    </div>
                  </form>
                )}
              </div>
            )}
          </section>

          {/* ── Section: 보안 ────────────────────────────────────── */}
          <section style={sectionCardStyle}>
            <h2 style={sectionTitleStyle}>보안</h2>
            <p style={{ fontSize: '14px', color: '#9494A0', marginBottom: '16px', marginTop: 0, lineHeight: 1.6 }}>
              로그인 시도, 토큰 발급 등 계정 활동 내역을 확인할 수 있습니다.
            </p>
            <Link href="/audit" style={{ textDecoration: 'none' }}>
              <button
                style={{
                  padding: '7px 16px',
                  borderRadius: '8px',
                  border: '1px solid var(--color-border, #2A2A35)',
                  backgroundColor: 'transparent',
                  color: 'var(--color-text-secondary, #9494A0)',
                  fontSize: '13px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  transition: 'border-color 0.15s, color 0.15s',
                }}
                onMouseEnter={(e) => {
                  const el = e.currentTarget as HTMLButtonElement;
                  el.style.borderColor = '#E8E8ED';
                  el.style.color = '#E8E8ED';
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget as HTMLButtonElement;
                  el.style.borderColor = 'var(--color-border, #2A2A35)';
                  el.style.color = 'var(--color-text-secondary, #9494A0)';
                }}
              >
                감사 로그 보기 →
              </button>
            </Link>
          </section>

          {/* ── Section 3: MCP 연결 가이드 ───────────────────────── */}
          <section style={sectionCardStyle}>
            <h2 style={sectionTitleStyle}>MCP 연결 가이드</h2>

            <p style={{ fontSize: '14px', color: '#9494A0', lineHeight: 1.7, marginBottom: '20px', marginTop: 0 }}>
              Claude Code의 <code style={{ fontFamily: 'monospace', fontSize: '13px', backgroundColor: 'rgba(255,255,255,0.07)', padding: '1px 6px', borderRadius: '4px', color: '#E8E8ED' }}>.mcp.json</code> 파일에 아래 설정을 추가하면 piLoci MCP 서버에 연결됩니다.
              <br />
              <code style={{ fontFamily: 'monospace', fontSize: '13px', backgroundColor: 'rgba(255,255,255,0.07)', padding: '1px 6px', borderRadius: '4px', color: '#E8E8ED' }}>YOUR_TOKEN_HERE</code> 부분을 위에서 발급한 API 토큰으로 교체하세요.
            </p>

            {/* Code block */}
            <div style={{ position: 'relative' }}>
              <pre
                style={{
                  backgroundColor: '#0F0F10',
                  border: '1px solid #2A2A35',
                  borderRadius: '10px',
                  padding: '20px',
                  fontSize: '13px',
                  lineHeight: 1.7,
                  color: '#E8E8ED',
                  fontFamily: 'monospace',
                  overflowX: 'auto',
                  margin: 0,
                  whiteSpace: 'pre',
                }}
              >
                {MCP_EXAMPLE}
              </pre>
              <button
                onClick={handleCopyMcp}
                style={{
                  position: 'absolute',
                  top: '12px',
                  right: '12px',
                  padding: '5px 12px',
                  borderRadius: '6px',
                  border: '1px solid #2A2A35',
                  backgroundColor: copiedMcp ? 'rgba(34,197,94,0.1)' : 'rgba(15,15,16,0.8)',
                  color: copiedMcp ? '#22C55E' : '#9494A0',
                  fontSize: '11px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  backdropFilter: 'blur(4px)',
                }}
              >
                {copiedMcp ? '복사됨!' : '복사'}
              </button>
            </div>

            <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div
                style={{
                  display: 'flex',
                  gap: '10px',
                  padding: '14px 16px',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(75,50,195,0.08)',
                  border: '1px solid rgba(75,50,195,0.2)',
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7C6CF0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, marginTop: '1px' }}>
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
                <p style={{ fontSize: '13px', color: '#9B8FE8', margin: 0, lineHeight: 1.6 }}>
                  <strong>user scope 토큰</strong>은 모든 프로젝트에 접근할 수 있습니다.
                  특정 프로젝트만 허용하려면 <strong>project scope 토큰</strong>을 사용하세요.
                </p>
              </div>
            </div>
          </section>

        </div>
      </main>
    </div>
  );
}
