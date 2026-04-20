/* eslint-disable */
// src/modules/monitoring/components/ActionPanel.jsx
import { useState, useEffect } from 'react';
import axios from 'axios';
import useGoldenTimer from '../hooks/useGoldenTimer';

// ── 레벨별 대응 버튼 목록 ─────────────────────────────────────
const ACTION_BUTTONS = {
  SLOW: [
    { id: 'VSL_DOWN_100_80', label: 'VSL 하향 권고 (100→80 km/h)' },
    { id: 'VMS_SLOW',        label: 'VMS 서행 안내 발령' },
  ],
  CONGESTED: [
    { id: 'VMS_DETOUR',     label: 'VMS 우회 안내 발령' },
    { id: 'VSL_DOWN_80_60', label: 'VSL 하향 (80→60 km/h)' },
    { id: 'RAMP_METERING',  label: '램프 미터링 권고' },
    { id: 'PATROL_REQUEST', label: '순찰대 출동 요청' },
  ],
  JAM: [
    { id: 'VMS_DETOUR',     label: 'VMS 우회 안내 발령' },
    { id: 'VSL_DOWN_80_60', label: 'VSL 하향 (80→60 km/h)' },
    { id: 'RAMP_METERING',  label: '램프 미터링 권고' },
    { id: 'PATROL_REQUEST', label: '순찰대 출동 요청' },
  ],
};

const REFERENCES = {
  SLOW:      'Papageorgiou 2006 / MDPI 2024 — 속도 분산 -12~20%, 정체 지속 -25%',
  CONGESTED: 'ALINEA 1991 / FHWA CHART — 골든타임 10분 이내 대응 시 처리시간 -11분',
  JAM:       'ALINEA 1991 / FHWA CHART — 골든타임 10분 이내 대응 시 처리시간 -11분',
};

const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };

export default function ActionPanel({ host, cameraId, cameraData }) {
  const [sentActions, setSentActions] = useState({});  // { action_id: 'HH:MM' }
  const [loadingMap,  setLoadingMap]  = useState({});  // { action_id: true }

  // 카메라 전환 시 발령 상태 초기화
  useEffect(() => {
    setSentActions({});
    setLoadingMap({});
  }, [cameraId]);

  const { level, is_learning, relearning, levelSince } = cameraData || {};
  const showLearning = is_learning || relearning;

  const { formatted: timerFormatted } = useGoldenTimer(level, levelSince);

  const handleAction = async (actionId) => {
    if (sentActions[actionId] || loadingMap[actionId]) return;

    // 현재 로그인 사용자 이름 (sessionStorage)
    const user     = JSON.parse(sessionStorage.getItem('user') || '{}');
    const actedBy  = user.name || '관리자';

    setLoadingMap(prev => ({ ...prev, [actionId]: true }));
    try {
      await axios.post(`https://${host}/api/monitoring/action`, {
        camera_id:   cameraId,
        action_type: actionId,
        acted_by:    actedBy,
      });
      const now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
      setSentActions(prev => ({ ...prev, [actionId]: now }));
    } catch {
      // 실패 시 로딩만 해제 (버튼 다시 누를 수 있음)
    } finally {
      setLoadingMap(prev => ({ ...prev, [actionId]: false }));
    }
  };

  // ── 빈 상태 ─────────────────────────────────────────────
  if (!cameraId) {
    return <Wrapper><Empty text="구간을 선택하세요" /></Wrapper>;
  }
  if (showLearning) {
    return <Wrapper><Empty text="학습 완료 후 대응 가능" sub={is_learning ? '도로 패턴 학습 중...' : '재보정 중...'} /></Wrapper>;
  }
  if (!level) {
    return <Wrapper><Empty text="데이터 수신 대기 중" /></Wrapper>;
  }

  const buttons = ACTION_BUTTONS[level] || [];

  return (
    <Wrapper>
      <div style={headerStyle}>🛠️ 대응 패널</div>

      {/* 원활: 정상 표시 */}
      {level === 'SMOOTH' && (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '6px' }}>
          <span style={{ fontSize: '20px' }}>✅</span>
          <span style={{ fontSize: '12px', color: '#22c55e', fontWeight: 600 }}>정상 운영 중</span>
        </div>
      )}

      {/* 서행/정체: 대응 버튼 */}
      {buttons.length > 0 && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
          {/* 레벨 타이틀 + 골든타임 타이머 */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <div style={{ fontSize: '11px', color: LEVEL_COLOR[level], fontWeight: 700 }}>
              {level === 'SLOW' ? '🟡 서행 구간 대응' : '🔴 정체 구간 대응'}
            </div>
            <div style={{ fontSize: '11px', fontWeight: 700, color: LEVEL_COLOR[level], fontVariantNumeric: 'tabular-nums' }}>
              ⏱ {timerFormatted}
            </div>
          </div>

          {/* 버튼 목록 */}
          {buttons.map(btn => (
            <ActionButton
              key={btn.id}
              label={btn.label}
              sent={sentActions[btn.id]}
              loading={!!loadingMap[btn.id]}
              onClick={() => handleAction(btn.id)}
            />
          ))}

          {/* 논문 근거 */}
          {REFERENCES[level] && (
            <div style={{
              marginTop: '10px', padding: '7px 8px',
              background: '#020617', borderRadius: '6px',
              fontSize: '10px', color: '#475569', lineHeight: 1.6,
              border: '1px solid #0f172a',
            }}>
              📚 {REFERENCES[level]}
            </div>
          )}
        </div>
      )}
    </Wrapper>
  );
}

// ── 대응 버튼 ─────────────────────────────────────────────────
function ActionButton({ label, sent, loading, onClick }) {
  if (sent) {
    return (
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '7px 10px', marginBottom: '4px',
        borderRadius: '6px', background: '#0f172a',
        border: '1px solid #1e293b',
        fontSize: '11px',
      }}>
        <span style={{ color: '#475569' }}>✓ {label}</span>
        <span style={{ color: '#334155', fontSize: '10px', flexShrink: 0, marginLeft: '6px' }}>
          발령완료 {sent}
        </span>
      </div>
    );
  }
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        display: 'block', width: '100%', marginBottom: '4px',
        padding: '7px 10px', borderRadius: '6px',
        background: loading ? '#0f172a' : '#1e3a5f',
        border: `1px solid ${loading ? '#1e293b' : '#2563eb44'}`,
        color: loading ? '#334155' : '#93c5fd',
        fontSize: '11px', textAlign: 'left',
        cursor: loading ? 'not-allowed' : 'pointer',
        transition: 'background 0.15s',
      }}
    >
      {loading ? '처리 중...' : label}
    </button>
  );
}

// ── 공통 래퍼 / 빈 상태 ──────────────────────────────────────
function Wrapper({ children }) {
  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      background: '#0f172a', borderRadius: '12px',
      border: '1px solid #1e293b', overflow: 'hidden',
    }}>
      {children}
    </div>
  );
}

function Empty({ text, sub }) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
      <span style={{ fontSize: '13px', color: '#334155' }}>{text}</span>
      {sub && <span style={{ fontSize: '11px', color: '#1e293b' }}>{sub}</span>}
    </div>
  );
}

const headerStyle = {
  padding: '10px 14px', borderBottom: '1px solid #1e293b',
  fontSize: '11px', fontWeight: 700, color: '#64748b',
  letterSpacing: '0.06em', flexShrink: 0,
};
