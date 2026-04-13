/* eslint-disable */
// src/modules/monitoring/components/SectionList.jsx
import { useState, useEffect, useCallback } from 'react';
import { fetchItsCctv, startSegment, stopSegment } from '../api';

const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444' };
const LEVEL_LABEL = { SMOOTH: '원활', SLOW: '서행', CONGESTED: '정체' };

const ROADS = [
  { key: 'gyeongbu',  label: '경부' },
  { key: 'gyeongin',  label: '경인' },
  { key: 'seohae',    label: '서해안' },
  { key: 'youngdong', label: '영동' },
  { key: 'jungang',   label: '중앙' },
];

export default function SectionList({ host, cameras, selectedId, onSelect, onViewItsCctv, onCctvListChange }) {
  const [road,        setRoad]        = useState('gyeongbu');
  const [cctvList,    setCctvList]    = useState([]);
  const [icList,      setIcList]      = useState([]);
  const [startIC,     setStartIC]     = useState('');
  const [endIC,       setEndIC]       = useState('');
  const [loadingCctv, setLoadingCctv] = useState(false);
  const [loadingSeg,  setLoadingSeg]  = useState(false);
  const [segError,    setSegError]    = useState('');
  const [showAllCctv, setShowAllCctv] = useState(false);

  // 고속도로 탭 변경 시 CCTV 목록 재조회
  useEffect(() => {
    if (!host) return;
    setLoadingCctv(true);
    setCctvList([]);
    setIcList([]);
    setStartIC('');
    setEndIC('');
    setSegError('');

    fetchItsCctv(host, road)
      .then(res => {
        const cameras_data = res.data.cameras || [];
        setCctvList(cameras_data);
        setIcList(res.data.ic_list || []);
        onCctvListChange?.(cameras_data);  // 부모에게 ITS 마커 목록 전달
      })
      .catch(() => setSegError('CCTV 목록 로드 실패'))
      .finally(() => setLoadingCctv(false));
  }, [road, host]);

  // IC 드롭다운 기본값: 첫/마지막 IC
  useEffect(() => {
    if (icList.length >= 2) {
      setStartIC(prev => prev || icList[0]);
      setEndIC(prev   => prev || icList[icList.length - 1]);
    }
  }, [icList]);

  const handleStartSegment = useCallback(async () => {
    if (!startIC || !endIC) { setSegError('시작/종료 IC를 선택하세요'); return; }
    setLoadingSeg(true);
    setSegError('');
    try {
      const res = await startSegment(host, road, startIC, endIC);
      const d   = res.data;
      setSegError(d.message || '완료');
    } catch (e) {
      const msg = e?.response?.data?.message || '구간 시작 실패 — 서버 확인';
      setSegError(msg);
    } finally {
      setLoadingSeg(false);
    }
  }, [host, road, startIC, endIC]);

  const handleStopSegment = useCallback(async () => {
    if (!startIC || !endIC) return;
    setLoadingSeg(true);
    setSegError('');
    try {
      const res = await stopSegment(host, road, startIC, endIC);
      setSegError(`${res.data.stopped.length}개 중지 완료`);
    } catch {
      setSegError('구간 중지 실패');
    } finally {
      setLoadingSeg(false);
    }
  }, [host, road, startIC, endIC]);

  // 현재 모니터링 중인 카메라 목록 (cameras prop에서 필터)
  const monitoringList = Object.values(cameras).sort((a, b) => {
    const order = { CONGESTED: 0, SLOW: 1, SMOOTH: 2 };
    return (order[a.level] ?? 3) - (order[b.level] ?? 3);
  });

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── 헤더 ── */}
      <div style={styles.header}>📍 구간 목록</div>

      {/* ── 고속도로 탭 ── */}
      <div style={styles.tabRow}>
        {ROADS.map(r => (
          <button
            key={r.key}
            onClick={() => setRoad(r.key)}
            style={{
              ...styles.tab,
              background:  road === r.key ? '#1e3a5f' : 'transparent',
              color:       road === r.key ? '#93c5fd' : '#475569',
              borderBottom: road === r.key ? '2px solid #3b82f6' : '2px solid transparent',
            }}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>

        {/* ── 구간 모니터링 설정 ── */}
        <div style={styles.segBox}>
          <div style={styles.segLabel}>구간 모니터링</div>

          {loadingCctv ? (
            <div style={styles.dimText}>CCTV 목록 로딩 중...</div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: '4px', marginBottom: '5px' }}>
                <IcSelect
                  label="시작"
                  value={startIC}
                  options={icList}
                  onChange={setStartIC}
                />
                <IcSelect
                  label="종료"
                  value={endIC}
                  options={[...icList].reverse()}
                  onChange={setEndIC}
                />
              </div>

              <div style={{ display: 'flex', gap: '4px' }}>
                <button
                  onClick={handleStartSegment}
                  disabled={loadingSeg}
                  style={{ ...styles.btn, flex: 2, background: '#1e3a5f', color: '#93c5fd', border: '1px solid #2563eb44' }}
                >
                  {loadingSeg ? '처리 중...' : '▶ 시작'}
                </button>
                <button
                  onClick={handleStopSegment}
                  disabled={loadingSeg}
                  style={{ ...styles.btn, flex: 1, background: 'transparent', color: '#475569', border: '1px solid #1e293b' }}
                >
                  ■ 중지
                </button>
              </div>

              {segError && (
                <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '4px', lineHeight: 1.4 }}>
                  {segError}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── 모니터링 중인 카메라 ── */}
        {monitoringList.length > 0 && (
          <div>
            <div style={styles.sectionTitle}>
              🔴 모니터링 중 ({monitoringList.length})
            </div>
            {monitoringList.map(cam => (
              <MonitoringItem
                key={cam.camera_id}
                cam={cam}
                selected={selectedId === cam.camera_id}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}

        {/* ── ITS CCTV 전체 목록 (접기/펼치기) ── */}
        <div>
          <button
            onClick={() => setShowAllCctv(v => !v)}
            style={styles.toggleBtn}
          >
            📷 ITS CCTV 전체 ({cctvList.length})
            <span style={{ marginLeft: '4px' }}>{showAllCctv ? '▲' : '▼'}</span>
          </button>

          {showAllCctv && (
            loadingCctv ? (
              <div style={styles.dimText}>로딩 중...</div>
            ) : cctvList.length === 0 ? (
              <div style={styles.dimText}>데이터 없음</div>
            ) : (
              cctvList.map(cam => {
                const monData = cameras[cam.camera_id];
                return (
                  <ItsCctvItem
                    key={cam.camera_id}
                    cam={cam}
                    isMonitoring={!!monData}
                    monData={monData}
                    onView={() => onViewItsCctv(cam)}
                  />
                );
              })
            )
          )}
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── IC 드롭다운 ──────────────────────────────────────────────
function IcSelect({ label, value, options, onChange }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: '9px', color: '#475569', marginBottom: '2px' }}>{label}</div>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width: '100%', boxSizing: 'border-box',
          background: '#020617', border: '1px solid #1e293b',
          borderRadius: '4px', padding: '3px 4px',
          color: '#e2e8f0', fontSize: '10px', outline: 'none',
        }}
      >
        {options.map(ic => (
          <option key={ic} value={ic}>{ic}</option>
        ))}
      </select>
    </div>
  );
}

// ── 모니터링 중 카메라 항목 ──────────────────────────────────
function MonitoringItem({ cam, selected, onSelect }) {
  const { camera_id, level, is_learning, relearning } = cam;
  const borderColor = selected ? (LEVEL_COLOR[level] || '#38bdf8') : 'transparent';

  return (
    <div
      onClick={() => onSelect(camera_id)}
      style={{
        padding: '8px 12px', cursor: 'pointer',
        borderBottom: '1px solid #0f172a',
        background: selected ? '#1e293b' : 'transparent',
        borderLeft: `3px solid ${borderColor}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
        <span style={{ fontSize: '11px', fontWeight: 600, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {cam.location || camera_id}
        </span>
        <LevelBadge level={level} isLearning={is_learning} relearning={relearning} />
      </div>
      {is_learning && (
        <div style={{ marginTop: '4px', fontSize: '9px', color: '#6b7280', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ display: 'inline-block', animation: 'spin 1.2s linear infinite' }}>⟳</span>
          학습 중 ({cam.learning_progress}/{cam.learning_total})
        </div>
      )}
    </div>
  );
}

// ── ITS CCTV 항목 ────────────────────────────────────────────
function ItsCctvItem({ cam, isMonitoring, monData, onView }) {
  let statusEl = null;
  if (isMonitoring && monData) {
    if (monData.is_learning || monData.relearning) {
      const prog = monData.learning_progress ?? 0;
      const tot  = monData.learning_total    ?? 0;
      statusEl = (
        <div style={{ fontSize: '9px', color: '#6b7280', marginTop: '1px', display: 'flex', alignItems: 'center', gap: '3px' }}>
          <span style={{ display: 'inline-block', animation: 'spin 1.2s linear infinite' }}>⟳</span>
          {monData.is_learning ? '학습중' : '재보정'} ({prog}/{tot})
        </div>
      );
    } else if (monData.level) {
      const c = LEVEL_COLOR[monData.level] || '#6b7280';
      statusEl = (
        <div style={{ fontSize: '9px', color: c, marginTop: '1px' }}>
          ● {LEVEL_LABEL[monData.level] || monData.level}
        </div>
      );
    }
  }

  return (
    <div style={{
      padding: '6px 10px', borderBottom: '1px solid #0f172a',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '10px', color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {cam.name}
        </div>
        {statusEl}
      </div>
      <button
        onClick={onView}
        style={{
          padding: '2px 7px', borderRadius: '4px', flexShrink: 0,
          background: 'transparent', border: '1px solid #1e293b',
          color: '#64748b', fontSize: '10px', cursor: 'pointer',
        }}
      >
        보기
      </button>
    </div>
  );
}

// ── 레벨 배지 ────────────────────────────────────────────────
function LevelBadge({ level, isLearning, relearning }) {
  if (isLearning || relearning) {
    return (
      <span style={{ ...styles.badge, background: '#374151', color: '#9ca3af', border: '1px solid #4b5563' }}>
        {isLearning ? '학습' : '재보정'}
      </span>
    );
  }
  const c = LEVEL_COLOR[level] || '#6b7280';
  return (
    <span style={{ ...styles.badge, background: `${c}22`, color: c, border: `1px solid ${c}44` }}>
      {LEVEL_LABEL[level] || '-'}
    </span>
  );
}

// ── 스타일 상수 ──────────────────────────────────────────────
const styles = {
  header: {
    padding: '10px 12px', borderBottom: '1px solid #1e293b',
    fontSize: '11px', fontWeight: 700, color: '#64748b',
    letterSpacing: '0.06em', flexShrink: 0,
  },
  tabRow: {
    display: 'flex', borderBottom: '1px solid #1e293b', flexShrink: 0, overflowX: 'auto',
  },
  tab: {
    flex: 1, padding: '5px 2px', fontSize: '10px', fontWeight: 600,
    cursor: 'pointer', border: 'none', borderRadius: 0, whiteSpace: 'nowrap',
    transition: 'color 0.15s',
  },
  segBox: {
    padding: '8px', borderBottom: '1px solid #1e293b',
    background: '#020617', flexShrink: 0,
  },
  segLabel: {
    fontSize: '10px', color: '#475569', fontWeight: 700,
    marginBottom: '6px', letterSpacing: '0.05em',
  },
  btn: {
    padding: '5px', borderRadius: '6px', fontSize: '11px',
    fontWeight: 600, cursor: 'pointer', textAlign: 'center',
  },
  sectionTitle: {
    padding: '6px 12px', fontSize: '10px', color: '#ef4444',
    fontWeight: 700, borderBottom: '1px solid #0f172a',
    background: '#0f172a',
  },
  toggleBtn: {
    width: '100%', padding: '7px 12px', textAlign: 'left',
    background: '#0a1628', border: 'none', borderBottom: '1px solid #1e293b',
    color: '#475569', fontSize: '10px', fontWeight: 700, cursor: 'pointer',
    display: 'flex', alignItems: 'center',
  },
  badge: {
    fontSize: '10px', padding: '2px 5px', borderRadius: '8px',
    fontWeight: 600, flexShrink: 0,
  },
  dimText: {
    padding: '8px 4px', fontSize: '10px', color: '#334155',
  },
};
