/* eslint-disable */
// src/modules/monitoring/components/MetricsPanel.jsx
import { useEffect, useRef, useState } from 'react';

const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };
const LEVEL_LABEL = { SMOOTH: '원활',    SLOW: '서행',    CONGESTED: '정체',    JAM: '정체'    };
const LEVEL_BG    = { SMOOTH: '#22c55e18', SLOW: '#eab30818', CONGESTED: '#ef444418', JAM: '#ef444418' };

function fmtDuration(sec) {
  if (!sec || sec <= 0) return '-';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function MetricsPanel({ data }) {
  const prevLevelRef = useRef(null);
  const [fade, setFade] = useState(false);

  // 레벨 전환 시 fade 애니메이션
  useEffect(() => {
    if (data?.level && prevLevelRef.current && prevLevelRef.current !== data.level) {
      setFade(true);
      const t = setTimeout(() => setFade(false), 500);
      return () => clearTimeout(t);
    }
    if (data?.level) prevLevelRef.current = data.level;
  }, [data?.level]);

  if (!data) {
    return (
      <div style={panelStyle}>
        <div style={headerStyle}>📊 실시간 지표</div>
        <div style={emptyStyle}>구간을 선택하세요</div>
      </div>
    );
  }

  const {
    level, is_learning, relearning,
    learning_progress, learning_total,
    jam_up, jam_down,
    vehicle_count, affected,
    occupancy, avg_speed, duration_sec,
  } = data;

  const showLearning = is_learning || relearning;
  const levelColor   = showLearning ? '#6b7280' : (LEVEL_COLOR[level] || '#6b7280');
  const levelLabel   = showLearning
    ? (is_learning ? '학습 중' : '재보정 중')
    : (LEVEL_LABEL[level] || '-');
  const levelBg      = showLearning ? '#37415118' : (LEVEL_BG[level] || '#37415118');
  const progressPct  = learning_total
    ? Math.min(Math.round((learning_progress / learning_total) * 100), 100)
    : 0;

  return (
    <div style={panelStyle}>
      <div style={headerStyle}>📊 실시간 지표</div>

      {/* 정체 레벨 뱃지 */}
      <div style={sectionStyle}>
        <div style={labelStyle}>정체 레벨</div>
        <div style={{
          display: 'inline-block',
          padding: '5px 14px',
          borderRadius: '20px',
          background: levelBg,
          border: `1px solid ${levelColor}44`,
          color: levelColor,
          fontSize: '14px',
          fontWeight: 700,
          transition: 'opacity 0.4s ease',
          opacity: fade ? 0.2 : 1,
        }}>
          {levelLabel}
        </div>
      </div>

      {/* 학습 진행 바 */}
      {showLearning && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={labelStyle}>{is_learning ? '초기 학습' : '재보정'} 진행</span>
            <span style={{ fontSize: '11px', color: '#64748b' }}>{progressPct}%</span>
          </div>
          <div style={{ background: '#1e293b', borderRadius: '6px', height: '6px', overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${progressPct}%`,
              background: '#38bdf8',
              borderRadius: '6px',
              transition: 'width 0.6s ease',
            }} />
          </div>
          <div style={{ fontSize: '10px', color: '#475569', marginTop: '4px', textAlign: 'right' }}>
            {learning_progress} / {learning_total} 프레임
          </div>
        </div>
      )}

      {/* 방향별 정체 지수 (상행 / 하행) */}
      {!showLearning && (
        <div style={sectionStyle}>
          {/* 평균 정체지수 바 제거 — 모델이 상/하행 방향별로 독립 판정하므로
              합산 평균은 의미가 없고 오히려 혼란을 줄 수 있어 방향별 수치만 표시 */}
          <span style={labelStyle}>정체 지수</span>
          <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
            <SmallBadge label="상행" value={(jam_up   ?? 0).toFixed(2)} />
            <SmallBadge label="하행" value={(jam_down ?? 0).toFixed(2)} />
          </div>
        </div>
      )}

      {/* 나머지 수치 지표 */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <MetricRow label="차량 수"   value={showLearning ? '-' : `${vehicle_count ?? 0}대`} />
        <MetricRow label="정체 차량" value={showLearning ? '-' : `${affected ?? 0}대`} />
        <MetricRow label="점유율"    value={showLearning ? '-' : `${((occupancy ?? 0) * 100).toFixed(1)}%`} />
        <MetricRow
          label="상대 속도"
          value={showLearning ? '-' : `기준 대비 ${Math.round((avg_speed ?? 0) * 100)}%`}
          sub="(정규화 속도, km/h 아님)"
        />
        <MetricRow
          label="지속 시간"
          value={(showLearning || level === 'SMOOTH') ? '-' : fmtDuration(duration_sec)}
        />
      </div>
    </div>
  );
}

// ── 서브 컴포넌트 ────────────────────────────────────────────


function SmallBadge({ label, value }) {
  return (
    <div style={{ flex: 1, background: '#1e293b', borderRadius: '6px', padding: '4px 8px', textAlign: 'center' }}>
      <div style={{ fontSize: '10px', color: '#64748b' }}>{label}</div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0' }}>{value}</div>
    </div>
  );
}

function MetricRow({ label, value, sub }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #0f172a' }}>
      <span style={{ fontSize: '12px', color: '#64748b' }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: '#e2e8f0' }}>{value}</div>
        {sub && <div style={{ fontSize: '10px', color: '#334155' }}>{sub}</div>}
      </div>
    </div>
  );
}

// ── 스타일 상수 ───────────────────────────────────────────────

const panelStyle  = { height: '100%', display: 'flex', flexDirection: 'column', background: '#0f172a', borderRadius: '12px', border: '1px solid #1e293b', overflow: 'hidden' };
const headerStyle = { padding: '10px 14px', borderBottom: '1px solid #1e293b', fontSize: '11px', fontWeight: 700, color: '#64748b', letterSpacing: '0.06em', flexShrink: 0 };
const sectionStyle= { padding: '12px 14px', borderBottom: '1px solid #1e293b', flexShrink: 0 };
const labelStyle  = { fontSize: '11px', color: '#64748b', marginBottom: '6px', display: 'block' };
const emptyStyle  = { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#334155', fontSize: '13px' };
