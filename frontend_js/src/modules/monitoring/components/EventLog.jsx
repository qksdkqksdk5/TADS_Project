/* eslint-disable */
// src/modules/monitoring/components/EventLog.jsx
// 역주행·정체 이벤트 목록을 보여주고 조치 완료/불필요 버튼으로 처리하는 컴포넌트
import { useState, useEffect } from 'react'; // React 훅 — 상태 관리(useState)와 사이드이펙트(useEffect)

// ── 경과 시간 훅 ──────────────────────────────────────────────────────────────
// 이벤트 수신 시각(received_at)으로부터 현재까지 몇 초가 지났는지 1초마다 갱신한다.
// ⚠️ detected_at(서버 UTC 나이브 문자열)을 쓰면 브라우저가 로컬 시간으로 잘못 해석해서
//    KST 환경에서 경과 시간이 9시간(32400초)만큼 부풀려지므로 반드시 received_at을 사용한다.
function useElapsed(received_at) {
  // elapsed: 경과 초 수 — 초기값 0, 1초마다 업데이트된다
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!received_at) return; // received_at 이 없으면 타이머를 시작하지 않음
    const base = received_at; // 이미 밀리초(ms) 타임스탬프이므로 new Date() 변환 불필요
    // 현재 시각에서 수신 시각을 빼고 1000으로 나눠 '몇 초 경과'를 구한다
    const update = () => setElapsed(Math.floor((Date.now() - base) / 1000));
    update(); // 컴포넌트가 마운트되자마자 한 번 즉시 실행해 0초 깜빡임 방지
    const t = setInterval(update, 1000); // 이후 1초마다 반복 실행
    return () => clearInterval(t); // 언마운트 시 인터벌 정리 — 메모리 누수 방지
  }, [received_at]); // received_at 이 바뀌면 타이머를 새로 시작한다

  return elapsed; // 호출 측에서 이 값을 받아 화면에 표시한다
}

// ── 경과 시간 숫자를 읽기 쉬운 문자열로 변환한다 ─────────────────────────────
// 60초 미만이면 "N초", 이상이면 "M분 N초" 형식으로 반환한다
function fmtElapsed(sec) {
  if (sec < 60) return `${sec}초`; // 1분 미만이면 초 단위로만 표시
  const m = Math.floor(sec / 60); // 총 경과 초 ÷ 60 = 분
  const s = sec % 60;             // 나머지 = 초
  return `${m}분 ${s}초`;         // "2분 35초" 형태로 반환
}

// ── 로그 한 행 컴포넌트 — 이벤트 하나를 3줄 레이아웃으로 표시한다 ─────────────
// 1줄: 아이콘 + 카메라 ID + 이벤트 유형 레이블
// 2줄: 감지 시각 + 경과 시간(또는 해소 사유)
// 3줄: 조치 완료 / 조치 불필요 버튼 (미해결 이벤트에만 표시)
function EventItem({ event, onSelect, onDismiss }) {
  // received_at(클라이언트 수신 ms 타임스탬프) 기준으로 경과 초 계산
  // detected_at 은 화면에 "감지 시각" 텍스트를 표시할 때만 사용한다
  const elapsed     = useElapsed(event.received_at);

  // 이벤트 종류 구분 — event_type 과 level 로 판단한다
  const isWrongway  = event.event_type === 'wrongway'; // 역주행 여부
  const isCongested = event.level === 'CONGESTED' || event.level === 'JAM'; // 심각한 정체 여부

  // 이벤트 종류에 따라 강조 색상과 아이콘을 결정한다
  // 역주행(주황) > 정체/JAM(빨강) > 서행(노랑) 순으로 심각도를 색으로 구분
  const accentColor = isWrongway ? '#f97316' : isCongested ? '#ef4444' : '#eab308';
  const icon        = isWrongway ? '⚠️'     : isCongested ? '🔴'      : '🟡';

  // 감지 시각 — "HH:MM:SS" 24시간제 형식으로만 표시해서 공간을 절약한다
  const timeStr = event.detected_at
    ? new Date(event.detected_at).toLocaleTimeString('ko-KR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      })
    : '-'; // detected_at 이 없으면 '-' 표시

  // 이벤트 유형 레이블 — 역주행과 정체를 다른 형식으로 표시한다
  // 정체: direction 필드가 있으면 "상행 SLOW (0.45)" 형태, 없으면 "SLOW (0.45)" 형태
  const labelText = isWrongway
    ? `역주행 (${event.label || event.track_id || '-'})` // 역주행: 차량 ID 또는 트랙 ID 표시
    : `${event.direction ? `${event.direction} ` : ''}${event.level} (${event.jam_score?.toFixed(2) ?? '-'})`;

  // 해소 사유 레이블 — 버튼 중 어느 쪽을 눌렀는지에 따라 텍스트가 결정된다
  const resolveLabel = event.resolve_reason === 'no_action' ? '조치 불필요' : '조치 완료';

  // 행 배경·테두리 스타일 — 해소 여부에 따라 달라진다
  // 해소된 이벤트: 배경 투명 + 투명도 낮춤(흐리게) → 새 이벤트와 시각적으로 구분
  // 미해결 이벤트: 강조 색상 배경 + 왼쪽 세로선 → 즉시 눈에 띔
  const rowStyle = event.is_resolved
    ? { background: 'transparent', opacity: 0.5 }
    : { background: `${accentColor}0d`, borderLeft: `3px solid ${accentColor}` };

  return (
    // 미해결 이벤트 클릭 시 해당 카메라를 화면에 선택한다
    // 해소된 이벤트는 클릭해도 아무 동작 없음(cursor: default)
    <div
      onClick={() => !event.is_resolved && onSelect(event.camera_id)}
      style={{
        padding: '5px 10px',
        borderBottom: '1px solid #0f172a',     // 행과 행 사이 구분선
        cursor: event.is_resolved ? 'default' : 'pointer', // 미해결만 클릭 가능
        fontSize: '11px',
        overflow: 'hidden',                    // 자식 요소가 컨테이너 밖으로 나가지 않도록 클리핑
        ...rowStyle,                           // 해소 여부에 따른 배경/테두리 적용
      }}
    >
      {/* ── 1줄: 아이콘 + 카메라 ID + 이벤트 레이블 ─────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', minWidth: 0 }}>

        {/* 심각도 아이콘 — flexShrink:0 으로 아이콘이 줄어들지 않게 고정 */}
        <span style={{ flexShrink: 0 }}>{icon}</span>

        {/* 카메라 ID — 최대 85px로 제한하고 넘치면 말줄임(…) 처리 */}
        <span style={{
          color: '#64748b', flexShrink: 0,
          maxWidth: '85px', overflow: 'hidden',
          textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {event.camera_id || '-'} {/* camera_id 가 없으면 '-' 표시 */}
        </span>

        {/* 이벤트 유형 레이블 — 해소 시 글씨 줄긋기 효과 + 색상 제거 */}
        <span style={{
          color: event.is_resolved ? '#475569' : accentColor, // 해소: 회색, 미해결: 강조색
          flex: 1, minWidth: 0,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: 600,
          textDecoration: event.is_resolved ? 'line-through' : 'none', // 해소 시 취소선
        }}>
          {labelText} {/* "역주행 (3)" 또는 "상행 SLOW (0.45)" 형태 */}
        </span>
      </div>

      {/* ── 2줄: 감지 시각 + 경과 시간(또는 해소 사유) ──────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        marginTop: '3px', minWidth: 0,
      }}>
        {/* 감지 시각 — HH:MM:SS 형식, 고정 너비(flexShrink:0)로 밀리지 않음 */}
        <span style={{ color: '#334155', flexShrink: 0, fontSize: '10px' }}>
          {timeStr}
        </span>

        {/* 빈 공간 — 감지 시각과 경과 시간 사이를 채워 양쪽 정렬 효과 */}
        <span style={{ flex: 1 }} />

        {/* 미해결 이벤트: 경과 시간("2분 35초") 표시 */}
        {!event.is_resolved && (
          <span style={{ color: '#475569', flexShrink: 0, fontSize: '10px' }}>
            {fmtElapsed(elapsed)} {/* 경과 시간을 읽기 좋은 형식으로 변환 */}
          </span>
        )}

        {/* 해소된 이벤트: 어떤 버튼으로 해소됐는지 사유 표시 */}
        {event.is_resolved && (
          <span style={{ color: '#334155', flexShrink: 0, fontSize: '10px' }}>
            {resolveLabel} {/* "조치 완료" 또는 "조치 불필요" */}
          </span>
        )}
      </div>

      {/* ── 3줄: 조치 버튼 — 미해결 이벤트에만 표시 ─────────────────────── */}
      {!event.is_resolved && (
        <div style={{
          display: 'flex', gap: '5px',
          marginTop: '5px',
        }}>
          {/* 조치 완료 버튼 — 클릭 시 reason: 'action' 으로 해소 처리 */}
          {/* e.stopPropagation(): 버튼 클릭이 부모 div(카메라 선택)로 전파되지 않도록 차단 */}
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(event.id, 'action'); }}
            style={{
              flex: 1,                           // 두 버튼이 공간을 반반 나눔
              background: 'transparent',
              border: `1px solid ${accentColor}`, // 강조 색 테두리
              color: accentColor,                 // 강조 색 텍스트
              padding: '2px 0',
              borderRadius: '4px',
              fontSize: '10px',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            조치 완료
          </button>

          {/* 조치 불필요 버튼 — 클릭 시 reason: 'no_action' 으로 해소 처리 */}
          {/* 실제로 조치가 필요 없었던 경우(오탐 등)에 사용한다 */}
          <button
            onClick={(e) => { e.stopPropagation(); onDismiss(event.id, 'no_action'); }}
            style={{
              flex: 1,                           // 두 버튼이 공간을 반반 나눔
              background: 'transparent',
              border: '1px solid #475569',        // 회색 테두리 — 덜 강조
              color: '#475569',                   // 회색 텍스트
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

// ── 메인 컴포넌트 — 이벤트 목록 전체를 감싸는 컨테이너 ──────────────────────────
// Props:
//   eventLogs    — 이벤트 배열 (useMonitoringSocket 에서 내려온다)
//   onSelectCamera — 카메라 ID를 받아 해당 카메라를 선택하는 콜백
//   onDismiss    — (eventId, reason) 으로 이벤트 해소 처리하는 콜백
export default function EventLog({ eventLogs, onSelectCamera, onDismiss }) {
  // 미해결 이벤트 수 — 헤더에 "미해결 N건" 배지로 표시한다
  const unresolvedCount = eventLogs.filter(e => !e.is_resolved).length;

  // 미해결 이벤트를 항상 목록 위에 정렬한다
  // 이유: 해소된 이벤트가 상단에 있으면 새로 발생한 미해결 이벤트를 놓칠 수 있기 때문
  // 동일 상태(미해결끼리, 해소끼리)는 원래 순서(최신순)를 유지한다
  const sorted = [...eventLogs].sort((a, b) => {
    if (a.is_resolved !== b.is_resolved) return a.is_resolved ? 1 : -1; // 미해결을 앞으로
    return 0; // 같은 상태끼리는 순서 변경 없음
  });

  return (
    // height:100% + flex column 으로 헤더를 고정하고 목록만 스크롤되게 만든다
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>

      {/* ── 헤더 — "이벤트 로그" 타이틀 + 미해결 배지 ─────────────────── */}
      <div style={{
        padding: '7px 12px',
        borderBottom: '1px solid #1e293b',          // 헤더와 목록 구분선
        fontSize: '11px', fontWeight: 700, color: '#64748b',
        flexShrink: 0,                              // 헤더가 목록에 밀려 줄어들지 않도록 고정
        display: 'flex', alignItems: 'center', gap: '8px',
      }}>
        📋 이벤트 로그

        {/* 미해결 이벤트가 1건 이상일 때만 빨간 배지를 표시한다 */}
        {unresolvedCount > 0 && (
          <span style={{
            background: '#ef444422', color: '#ef4444',
            border: '1px solid #ef444444',
            borderRadius: '10px', padding: '1px 7px',
            fontSize: '10px', fontWeight: 700,
          }}>
            미해결 {unresolvedCount}건 {/* 미해결 수를 숫자로 표시 */}
          </span>
        )}
      </div>

      {/* ── 목록 — 스크롤 가능한 이벤트 행들 ──────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto' }}> {/* flex:1 로 헤더 제외 남은 공간 전부 차지 */}

        {/* 이벤트가 없을 때 안내 문구 표시 */}
        {sorted.length === 0 ? (
          <div style={{ padding: '16px', textAlign: 'center', color: '#1e293b', fontSize: '12px' }}>
            이벤트 없음
          </div>
        ) : (
          // 정렬된 이벤트 배열을 EventItem 컴포넌트로 렌더링한다
          sorted.map(ev => (
            <EventItem
              key={ev.id}           // React 재조정(reconciliation)을 위한 고유 키
              event={ev}            // 이벤트 데이터 전달
              onSelect={onSelectCamera} // 카메라 선택 콜백 전달
              onDismiss={onDismiss} // 조치 처리 콜백 전달
            />
          ))
        )}
      </div>
    </div>
  );
}
