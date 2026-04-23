'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ApiToken, Project } from '@/lib/types';

interface NewTokenResult {
  token: string;
  token_id: string;
  name: string;
}

export function TokenManager() {
  const queryClient = useQueryClient();

  // List tokens
  const { data: tokens = [], isLoading: tokensLoading, error: tokensError } = useQuery<ApiToken[]>({
    queryKey: ['tokens'],
    queryFn: () => api.listTokens(),
  });

  // List projects (for project-scope token creation)
  const { data: projects = [] } = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: () => api.listProjects(),
  });

  // Revoke mutation
  const revokeMutation = useMutation({
    mutationFn: (tokenId: string) => api.revokeToken(tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tokens'] });
    },
  });

  // Create mutation
  const createMutation = useMutation({
    mutationFn: ({ name, scope, project_id }: { name: string; scope: 'project' | 'user'; project_id?: string }) =>
      api.createToken(name, scope, project_id) as Promise<NewTokenResult>,
    onSuccess: (data) => {
      setNewTokenResult(data as NewTokenResult);
      queryClient.invalidateQueries({ queryKey: ['tokens'] });
      setShowCreateForm(false);
      setFormName('');
      setFormScope('user');
      setFormProjectId('');
    },
  });

  // Form state
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formScope, setFormScope] = useState<'project' | 'user'>('user');
  const [formProjectId, setFormProjectId] = useState('');

  // Revealed token state
  const [newTokenResult, setNewTokenResult] = useState<NewTokenResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const handleRevoke = (token: ApiToken) => {
    if (window.confirm(`"${token.name}" 토큰을 폐기하시겠습니까? 이 작업은 되돌릴 수 없습니다.`)) {
      revokeMutation.mutate(token.token_id);
    }
  };

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formName.trim()) return;
    createMutation.mutate({
      name: formName.trim(),
      scope: formScope,
      project_id: formScope === 'project' && formProjectId ? formProjectId : undefined,
    });
  };

  const handleCopy = async () => {
    if (!newTokenResult) return;
    try {
      await navigator.clipboard.writeText(newTokenResult.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard not available
    }
  };

  const handleCloseReveal = () => {
    setNewTokenResult(null);
    setCopied(false);
    setConfirmed(false);
  };

  const projectById = (id: string) => projects.find((p) => p.id === id);

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString('ko-KR', { year: 'numeric', month: 'short', day: 'numeric' });

  // ── Styles ──────────────────────────────────────────────────────────
  const cardStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-surface-raised, #1A1A1F)',
    border: '1px solid var(--color-border, #2A2A35)',
    borderRadius: '12px',
    padding: '20px',
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

  const btnPrimaryStyle: React.CSSProperties = {
    padding: '8px 18px',
    borderRadius: '8px',
    border: 'none',
    backgroundColor: 'var(--color-brand, #4B32C3)',
    color: '#fff',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
  };

  const btnSecondaryStyle: React.CSSProperties = {
    padding: '8px 18px',
    borderRadius: '8px',
    border: '1px solid var(--color-border, #2A2A35)',
    backgroundColor: 'transparent',
    color: 'var(--color-text-secondary, #9494A0)',
    fontSize: '14px',
    fontWeight: 500,
    cursor: 'pointer',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* ── Revealed Token Modal ──────────────────────────────────── */}
      {newTokenResult && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0,0,0,0.7)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
          }}
        >
          <div
            style={{
              backgroundColor: '#1A1A1F',
              border: '1px solid #2A2A35',
              borderRadius: '16px',
              padding: '32px',
              maxWidth: '520px',
              width: '100%',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <span
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(34,197,94,0.15)',
                  color: '#22C55E',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
              <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#E8E8ED', margin: 0 }}>
                토큰이 발급되었습니다
              </h3>
            </div>
            <p style={{ fontSize: '13px', color: '#EF4444', marginBottom: '20px', marginTop: '4px' }}>
              이 토큰은 다시 볼 수 없습니다. 지금 복사하세요.
            </p>

            {/* Token display */}
            <div
              style={{
                backgroundColor: '#0F0F10',
                border: '1px solid #2A2A35',
                borderRadius: '8px',
                padding: '12px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                marginBottom: '20px',
              }}
            >
              <code
                style={{
                  flex: 1,
                  fontSize: '12px',
                  color: '#E8E8ED',
                  fontFamily: 'monospace',
                  wordBreak: 'break-all',
                  lineHeight: 1.6,
                }}
              >
                {newTokenResult.token}
              </code>
              <button
                onClick={handleCopy}
                style={{
                  flexShrink: 0,
                  padding: '6px 12px',
                  borderRadius: '7px',
                  border: '1px solid #2A2A35',
                  backgroundColor: copied ? 'rgba(34,197,94,0.1)' : 'transparent',
                  color: copied ? '#22C55E' : '#9494A0',
                  fontSize: '12px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  whiteSpace: 'nowrap',
                }}
              >
                {copied ? '복사됨!' : '복사'}
              </button>
            </div>

            {/* Confirm checkbox */}
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                cursor: 'pointer',
                marginBottom: '20px',
                fontSize: '14px',
                color: '#9494A0',
                userSelect: 'none',
              }}
            >
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                style={{ width: '16px', height: '16px', cursor: 'pointer', accentColor: '#4B32C3' }}
              />
              토큰을 안전한 곳에 저장했습니다
            </label>

            <button
              onClick={handleCloseReveal}
              disabled={!confirmed}
              style={{
                ...btnPrimaryStyle,
                width: '100%',
                opacity: confirmed ? 1 : 0.4,
                cursor: confirmed ? 'pointer' : 'not-allowed',
              }}
            >
              닫기
            </button>
          </div>
        </div>
      )}

      {/* ── Header row ───────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <p style={{ fontSize: '13px', color: '#9494A0', margin: 0 }}>
          API 토큰으로 MCP 서버 또는 외부 클라이언트에서 piLoci에 접근할 수 있습니다.
        </p>
        <button
          onClick={() => setShowCreateForm((v) => !v)}
          style={showCreateForm ? btnSecondaryStyle : btnPrimaryStyle}
        >
          {showCreateForm ? '취소' : '+ 새 토큰 발급'}
        </button>
      </div>

      {/* ── Create form ──────────────────────────────────────────── */}
      {showCreateForm && (
        <div style={cardStyle}>
          <h4 style={{ fontSize: '14px', fontWeight: 600, color: '#E8E8ED', marginBottom: '16px', marginTop: 0 }}>
            새 API 토큰 발급
          </h4>
          <form onSubmit={handleCreate}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {/* Name */}
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: '#9494A0', marginBottom: '6px' }}>
                  토큰 이름
                </label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="예: Claude Code 로컬"
                  required
                  style={inputStyle}
                />
              </div>

              {/* Scope */}
              <div>
                <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: '#9494A0', marginBottom: '10px' }}>
                  범위 (Scope)
                </label>
                <div style={{ display: 'flex', gap: '12px' }}>
                  {(['user', 'project'] as const).map((scope) => (
                    <label
                      key={scope}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        cursor: 'pointer',
                        padding: '10px 16px',
                        borderRadius: '8px',
                        border: `1px solid ${formScope === scope ? '#4B32C3' : '#2A2A35'}`,
                        backgroundColor: formScope === scope ? 'rgba(75,50,195,0.1)' : 'transparent',
                        fontSize: '13px',
                        fontWeight: 500,
                        color: formScope === scope ? '#9B8FE8' : '#9494A0',
                        transition: 'all 0.15s',
                        flex: 1,
                        justifyContent: 'center',
                        userSelect: 'none',
                      }}
                    >
                      <input
                        type="radio"
                        name="scope"
                        value={scope}
                        checked={formScope === scope}
                        onChange={() => {
                          setFormScope(scope);
                          if (scope === 'user') setFormProjectId('');
                        }}
                        style={{ accentColor: '#4B32C3' }}
                      />
                      {scope === 'user' ? '사용자 전체' : '프로젝트'}
                    </label>
                  ))}
                </div>
              </div>

              {/* Project select */}
              {formScope === 'project' && (
                <div>
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: '#9494A0', marginBottom: '6px' }}>
                    프로젝트
                  </label>
                  <select
                    value={formProjectId}
                    onChange={(e) => setFormProjectId(e.target.value)}
                    required
                    style={{ ...inputStyle, cursor: 'pointer' }}
                  >
                    <option value="">-- 프로젝트 선택 --</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.slug})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {createMutation.error && (
                <p style={{ fontSize: '13px', color: '#EF4444', margin: 0 }}>
                  {(createMutation.error as Error).message}
                </p>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', paddingTop: '4px' }}>
                <button
                  type="button"
                  onClick={() => setShowCreateForm(false)}
                  style={btnSecondaryStyle}
                >
                  취소
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending || !formName.trim() || (formScope === 'project' && !formProjectId)}
                  style={{
                    ...btnPrimaryStyle,
                    opacity: createMutation.isPending || !formName.trim() || (formScope === 'project' && !formProjectId) ? 0.5 : 1,
                    cursor: createMutation.isPending ? 'wait' : 'pointer',
                  }}
                >
                  {createMutation.isPending ? '발급 중...' : '발급'}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* ── Token list ───────────────────────────────────────────── */}
      {tokensLoading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#9494A0', fontSize: '14px' }}>
          로딩 중...
        </div>
      ) : tokensError ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#EF4444', fontSize: '14px' }}>
          토큰 목록을 불러오지 못했습니다.
        </div>
      ) : tokens.length === 0 ? (
        <div
          style={{
            ...cardStyle,
            textAlign: 'center',
            padding: '48px 24px',
            color: '#9494A0',
            fontSize: '14px',
          }}
        >
          발급된 토큰이 없습니다.
        </div>
      ) : (
        <div style={cardStyle}>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {tokens.map((token, idx) => {
              const project = token.project_id ? projectById(token.project_id) : undefined;
              return (
                <div
                  key={token.token_id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    gap: '12px',
                    padding: '14px 0',
                    borderBottom: idx < tokens.length - 1 ? '1px solid #2A2A35' : 'none',
                    flexWrap: 'wrap',
                  }}
                >
                  {/* Token info */}
                  <div style={{ flex: 1, minWidth: '200px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '6px' }}>
                      <span style={{ fontSize: '14px', fontWeight: 600, color: '#E8E8ED' }}>
                        {token.name}
                      </span>
                      {/* Scope badge */}
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: 600,
                          padding: '2px 8px',
                          borderRadius: '999px',
                          backgroundColor: token.scope === 'user'
                            ? 'rgba(75,50,195,0.15)'
                            : 'rgba(34,197,94,0.12)',
                          color: token.scope === 'user' ? '#7C6CF0' : '#22C55E',
                          letterSpacing: '0.02em',
                          textTransform: 'uppercase',
                        }}
                      >
                        {token.scope === 'user' ? 'user' : 'project'}
                      </span>
                      {/* Project slug */}
                      {project && (
                        <span
                          style={{
                            fontSize: '11px',
                            fontFamily: 'monospace',
                            padding: '2px 8px',
                            borderRadius: '6px',
                            backgroundColor: 'rgba(255,255,255,0.05)',
                            color: '#9494A0',
                          }}
                        >
                          {project.slug}
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '12px', color: '#9494A0' }}>
                        발급: {formatDate(token.created_at)}
                      </span>
                      {token.last_used_at && (
                        <span style={{ fontSize: '12px', color: '#9494A0' }}>
                          마지막 사용: {formatDate(token.last_used_at)}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Revoke button */}
                  <button
                    onClick={() => handleRevoke(token)}
                    disabled={revokeMutation.isPending}
                    style={{
                      padding: '6px 14px',
                      borderRadius: '7px',
                      border: '1px solid #2A2A35',
                      backgroundColor: 'transparent',
                      color: '#9494A0',
                      fontSize: '12px',
                      fontWeight: 500,
                      cursor: revokeMutation.isPending ? 'wait' : 'pointer',
                      transition: 'all 0.15s',
                      flexShrink: 0,
                    }}
                    onMouseEnter={(e) => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = '#EF4444';
                      el.style.color = '#EF4444';
                      el.style.backgroundColor = 'rgba(239,68,68,0.08)';
                    }}
                    onMouseLeave={(e) => {
                      const el = e.currentTarget as HTMLButtonElement;
                      el.style.borderColor = '#2A2A35';
                      el.style.color = '#9494A0';
                      el.style.backgroundColor = 'transparent';
                    }}
                  >
                    폐기
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
