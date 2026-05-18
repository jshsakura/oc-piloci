/**
 * Korean relative-time formatter used by the wiki to surface how fresh
 * each note is ("3일 전") without leaning on a full date library. Falls
 * back to "방금" under a minute, switches to years past 365 days.
 */
export function relTimeKr(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 60) return "방금";
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`;
  if (sec < 86400 * 30) return `${Math.floor(sec / 86400)}일 전`;
  if (sec < 86400 * 365) return `${Math.floor(sec / (86400 * 30))}달 전`;
  return `${Math.floor(sec / (86400 * 365))}년 전`;
}
