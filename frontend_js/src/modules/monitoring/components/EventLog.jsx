/* eslint-disable */
// src/modules/monitoring/components/EventLog.jsx
import { useState, useEffect } from 'react';

// ── 경과 시간 훅 ──────────────────────────────────────────────
// received_at: 클라이언트가 이벤트를 수신한 시각(ms).
// detected_at(UTC 나이브 문자열)을 쓰면 브라우저가 로컬 시간으로 오해석해
// KST 환경에서 경과 시간이 9시간만큼 부풀려지므로 received_at 을 사용한다.
function useElapsed(received_at) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!received_at) return; // received_at 없으면 카운트 중지
    const base = received_at; // 이미 ms 타임스탬프 — new Date() 변환 불필요
    const update = () => setElapsed(Math.floor((Date.now() - base) / 1000));
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t); // 언마운트 시 인터벌 정리
  }, [received_at]);
  return elapsed;
}

function fmtElapsed(sec) {
  if (sec < 60) return `${sec}초`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}분 ${s}초`;
}

// ── 로그 한 행 (3줄 레이아웃) ────────────────────────────────
// 1줄: 아이콘 + 카메라 ID + 이벤트 유형 레이블
// 2줄: 감지 시각 + 경과 시간
// 3줄: 조치 완료 버튼 + 조치 불필요 버튼 (미해결 이벤트에만 표시)
function EventItem({ event, onSelect, onDismiss }) {
  // received_at(클라이언트 수신 ms) 기준으로 경과 시간 계산
  // detected_at 은 감지 시각 표시용으로만 사용한다
  const elapsed     = useElapsed(event.received_at);
  const isWrongway  = event.event_type === 'wrongway';
  const isCongested = event.level === 'CONGESTED' || event.level === 'JAM';

  // 이벤트 종류에 따라 강조 색상과 아이콘 결정
  const accentColor = isWrongway ? '#f97316' : isCongested ? '#ef4444' : '#eab308';
  const icon        = isWrongway ? '⚠️'     : isCongested ? '🔴'      : '🟡';

  // 감지 시각 — HH:MM:SS 형식으로만 표시 (AM/PM 없애 공간 절약)
  const timeStr = event.detected_at
    ? new Date(event.detected_at).toLocaleTimeString('ko-KR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      })
    : '-';

  // 이벤트 유형 레이블 텍스트
  // direction 필드가 있으면 "상행 SLOW (0.45)" 형태로, 없으면 기존 형태로 표시한다.
  const labelText = isWrongway
    ? `역주행 (${event.label || event.track_id || '-'})`
    : `${event.direction ? `${event.direction} ` : ''}${event.level} (${event.jam_score?.toFixed(2) ?? '-'})`;

  // 해소 사유 텍스트 — resolve_reason 값에 따라 결정
  const resolveLabel = event.resolve_reason === 'no_action' ? '조치 불필요' : '조치 완료';

  // 해소 여부에 따른 행 배경·테두리 스타일
  // 해소된 경우: 배경색·테두리 모두 제거하고 투명도 낮춤
  const rowStyle = event.is_resolved
    ? { background: 'transparent', opacity: 0.5 }
    : { background: `${accentColor}0d`, borderLeft: `3px solid ${accentColor}` };

  return (
    <div
      onClick={() => !event.is_resolved && onSelect(event.camera_id)}
      style={{
        padding: '5px 10px',
        borderBottom: '1px solid #0f172a',
        cursor: event.is_resolved ? 'default' : 'pointer',
        fontSize: '11px',
        overflow: 'hidden', // 자식이 컨테이너 밖으로 나가지 않도록 클리핑
        ...rowStyle,
      }}
    >
      {/* ── 1줄: 아이콘 + 카메라 ID + 레이블 ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', minWidth: 0 }}>
        {/* 아이콘 — 너비 고정 */}
        <span style={{ flexShrink: 0 }}>{icon}</span>

        {/* 카메라 ID — 최대 85px, 초과 시 말줄임 */}
        <span style={{
          color: '#64748b', flexShrink: 0,
          maxWidth: '85px', overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {event.camera_id || '-'}
        </span>

        {/* 이벤트 유형 레이블 — 해소 시 색상 제거 + 줄긋기 효과 */}
        <span style={{
          color: event.is_resolved ? '#475569' : accentColor,
          flex: 1, minWidth: 0,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: 600,
          textDecoration: event.is_resolved ? 'line-through' : 'none', // 해소 시 글씨 줄긋기
        }}>
          {labelText}
        </span>
      </div>

      {/* ── 2줄: 감지 시각 + 경과 시간 또는 해소 사유 ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        marginTop: '3px', minWidth: 0,
      }}>
        {/* 감지 시각 — 고정 너비 */}
        <span style={{ color: '#334155', flexShrink: 0, fontSize: '10px' }}>
          {timeStr}
        </span>

        {/* 빈 공간 채우기 */}
        <span style={{ flex: 1 }} />

        {/* 미해결: 경과 시간 표시 / 해소됨: 조치 완료 or 조치 불필요 표시 */}
        {!event.is_resolved && (
          <span style={{ color: '#475569', flexShrink: 0, fontSize: '10px' }}>
            {fmtElapsed(elapsed)}
          </span>
        )}
        {event.is_resolved && (
          <span style={{ color: '#334155', flexShrink: 0, fontSize: '10px' }}>
            {resolveLabel}
          </span>
        )}
      </div>

      {/* ── 3줄: 조치 버튼 2개 — 미해결 이벤트에만 표시 ── */}
      {!event.is_resolved && (
        <div style={{
          display: 'flex', gap: '5px',
          marginTop: '5px',
        }}>
          {/* 조치 완료 버튼 — 클릭 시 해소 처리 (reason: 'action') */}
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(event.id, 'action'); }}
            style={{
              flex: 1,                        // 버튼 두 개가 공간을 반반 나눔
              background: 'transparent',
              border: `1px solid ${accentColor}`,
              color: accentColor,
              padding: '2px 0',
              borderRadius: '4px',
              fontSize: '10px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            조치 완료
          </button>

          {/* 조치 불필요 버튼 — 클릭 시 해소 처리 (reason: 'no_action') */}
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(event.id, 'no_action'); }}
            style={{
              flex: 1,                        // 버튼 두 개가 공간을 반반 나눔
              background: 'transparent',
              border: '1px solid #475569',
              color: '#475569',
              padding: '2px 0',
              borderRadius: '4px',
              fontSize: '10px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            조치 불필요
          </button>
        </div>
      )}
    </div>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
// onDismiss(eventId, reason): 조치 완료('action') 또는 조치 불필요('no_action') 처리 콜백
export default function EventLog({ eventLogs, onSelectCamera, onDismiss }) {
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
              onDismiss={onDismiss}
            />
          ))
        )}
      </div>
    </div>
  );
}
