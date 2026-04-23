# Security Policy

## Supported Versions
최신 태그 버전만 지원.

## Reporting a Vulnerability
취약점 발견 시 GitHub Security Advisories (private)로 신고.
공개 Issue 금지.
응답 SLA: 7일 이내 acknowledgement, 90일 이내 패치.

## Security Design
- 비밀번호: argon2id (OWASP 2024)
- 세션: Redis, 14일 TTL
- JWT: HS256, 90일 만료, 수동 폐기 가능
- 데이터 격리: 모든 쿼리에 (user_id, project_id) 필터 강제
- 외부 노출: Cloudflare Tunnel 전용 (포트포워딩 금지)
- 컨테이너: non-root (UID 1000), read-only rootfs, capabilities drop ALL
