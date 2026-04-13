/* eslint-disable */
// src/modules/monitoring/components/EventLog.jsx
import { useState, useEffect } from 'react';

// ── 경과 시간 훅 ──────────────────────────────────────────────
function useElapsed(detected_at) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!detected_at) return;
    const base = new Date(detected_at).getTime();
    const update = () => setElapsed(Math.floor((Date.now() - base) / 1000));
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, [detected_at]);
  return elapsed;
}

function fmtElapsed(sec) {
  if (sec < 60) return `${sec}초`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}분 ${s}초`;
}

// ── 로그 한 행 ────────────────────────────────────────────────
function EventItem({ event, onSelect, onDismissWrongway }) {
  const elapsed    = useElapsed(event.detected_at);
  const isWrongway = event.event_type === 'wrongway';
  const isCongested = event.level === 'CONGESTED';

  const accentColor = isWrongway ? '#f97316' : isCongested ? '#ef4444' : '#eab308';
  const icon        = isWrongway ? '⚠️' : isCongested ? '🔴' : '🟡';

  const timeStr = event.detected_at
    ? new Date(event.detected_at).toLocaleTimeString('ko-KR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })
    : '-';

  const rowStyle = event.is_resolved
    ? { background: 'transparent', opacity: 0.45, textDecoration: 'line-through' }
    : {
        background: `${accentColor}0d`,
        borderLeft: `3px solid ${accentColor}`,
      };

  return (
    <div
      onClick={() => !event.is_resolved && onSelect(event.camera_id)}
      style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        padding: '6px 12px',
        borderBottom: '1px solid #0f172a',
        cursor: event.is_resolved ? 'default' : 'pointer',
        fontSize: '11px',
        ...rowStyle,
      }}
    >
      <span style={{ flexShrink: 0 }}>{icon}</span>
      <span style={{ color: '#475569', flexShrink: 0 }}>{timeStr}</span>
      <span style={{ color: '#64748b', flexShrink: 0, maxWidth: '80px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {event.camera_id || '-'}
      </span>
      <span style={{ color: event.is_resolved ? '#475569' : accentColor, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {isWrongway
          ? `역주행 감지 (${event.label || event.track_id || '-'})`
          : `${event.level} (지수: ${event.jam_score?.toFixed(2) ?? '-'})`}
      </span>

      {/* 경과 시간 or 해소 표시 */}
      {!event.is_resolved && (
        <span style={{ color: '#475569', flexShrink: 0 }}>{fmtElapsed(elapsed)}</span>
      )}
      {event.is_resolved && (
        <span style={{ color: '#334155', flexShrink: 0 }}>해소됨</span>
      )}

      {/* 역주행 경보 해제 버튼 */}
      {isWrongway && !event.is_resolved && (
        <button
          onClick={(e) => { e.stopPropagation(); onDismissWrongway(event.id); }}
          style={{
            background: 'transparent',
            border: `1px solid #f97316`,
            color: '#f97316',
            padding: '2px 7px',
            borderRadius: '4px',
            fontSize: '10px',
            cursor: 'pointer',
            flexShrink: 0,
            fontWeight: 600,
          }}
        >
          경보 해제
        </button>
      )}
    </div>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function EventLog({ eventLogs, onSelectCamera, onDismissWrongway }) {
  const unresolvedCount = eventLogs.filter(e => !e.is_resolved).length;

  // 미해결 상단 정렬, 동일 상태끼리는 최신순 유지
  const sorted = [...eventLogs].sort((a, b) => {
    if (a.is_resolved !== b.is_resolved) return a.is_resolved ? 1 : -1;
    return 0;
  });

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 헤더 */}
      <div style={{
        padding: '7px 12px',
        borderBottom: '1px solid #1e293b',
        fontSize: '11px', fontWeight: 700, color: '#64748b',
        flexShrink: 0, display: 'flex', alignItems: 'center', gap: '8px',
      }}>
        📋 이벤트 로그
        {unresolvedCount > 0 && (
          <span style={{
            background: '#ef444422', color: '#ef4444',
            border: '1px solid #ef444444',
            borderRadius: '10px', padding: '1px 7px',
            fontSize: '10px', fontWeight: 700,
          }}>
            미해결 {unresolvedCount}건
          </span>
        )}
      </div>

      {/* 목록 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {sorted.length === 0 ? (
          <div style={{ padding: '16px', textAlign: 'center', color: '#1e293b', fontSize: '12px' }}>
            이벤트 없음
          </div>
        ) : (
          sorted.map(ev => (
            <EventItem
              key={ev.id}
              event={ev}
              onSelect={onSelectCamera}
              onDismissWrongway={onDismissWrongway}
            />
          ))
        )}
      </div>
    </div>
  );
}
