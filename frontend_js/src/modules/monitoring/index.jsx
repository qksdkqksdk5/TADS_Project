/* eslint-disable */
// src/modules/monitoring/index.jsx
import { useState, useEffect, useCallback } from 'react';
import { useMonitoringSocket } from './hooks/useMonitoringSocket';
import { useSoundAlert }       from './hooks/useSoundAlert';
import SectionList   from './components/SectionList';
import MetricsPanel  from './components/MetricsPanel';
import MonitoringMap from './components/MonitoringMap';
import CctvPlayer    from './components/CctvPlayer';
import EventLog      from './components/EventLog';
import ActionPanel   from './components/ActionPanel';
import { fetchItsCctv } from './api';

// ── 시계 ─────────────────────────────────────────────────────
function Clock() {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span>
      {time.toLocaleTimeString('ko-KR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })}
    </span>
  );
}

// ── LIVE 점 ───────────────────────────────────────────────────
function LiveDot({ connected }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
      <span style={{
        width: '7px', height: '7px', borderRadius: '50%',
        background: connected ? '#22c55e' : '#475569',
        display: 'inline-block',
        animation: connected ? 'pulse-dot 1.5s infinite' : 'none',
      }} />
      <span style={{ fontSize: '11px', fontWeight: 600, color: connected ? '#22c55e' : '#475569' }}>
        {connected ? 'LIVE' : 'OFFLINE'}
      </span>
    </div>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function MonitoringModule({ host, isMobile }) {
  const [selectedId,    setSelectedId]    = useState(null);
  const [soundOn,       setSoundOn]       = useState(true);
  const [flashActive,   setFlashActive]   = useState(false);
  const [selectedItsCctv, setSelectedItsCctv] = useState(null);  // ITS 보기 전용 CCTV
  const [itsCctvList,   setItsCctvList]   = useState([]);         // 지도에 표시할 ITS 마커 목록

  // ── 사운드 훅 ─────────────────────────────────────────────
  const {
    playAlert, playResolved,
    startWrongwayAlarm, stopWrongwayAlarm,
    startCongestionRepeat, stopCongestionRepeat,
  } = useSoundAlert(soundOn);

  // ── 소켓 훅 (콜백 연결) ───────────────────────────────────
  const { cameras, eventLogs, unresolvedCounts, connected, emitSelectCamera, resolveEvent } =
    useMonitoringSocket(host, {
      onAnomalyAlert: useCallback((data) => {
        playAlert(data.level);
        if (data.level === 'CONGESTED' || data.level === 'JAM') {
          setFlashActive(true);
          setTimeout(() => setFlashActive(false), 2500);
        }
      }, [playAlert]),

      onWrongwayAlert: useCallback(() => {
        startWrongwayAlarm();
      }, [startWrongwayAlarm]),

      onResolved: useCallback(() => {
        playResolved();
        stopCongestionRepeat();
      }, [playResolved, stopCongestionRepeat]),
    });

  // ── CONGESTED 5분+ → 30초 반복 경보 ──────────────────────
  useEffect(() => {
    const hasProlonged = Object.values(cameras).some(
      c => (c.level === 'CONGESTED' || c.level === 'JAM') && (c.duration_sec ?? 0) > 300
    );
    if (hasProlonged) startCongestionRepeat();
    else              stopCongestionRepeat();
  }, [cameras, startCongestionRepeat, stopCongestionRepeat]);

  // ── ITS CCTV 보기 핸들러 ─────────────────────────────────
  const handleViewItsCctv = useCallback((cam) => {
    setSelectedItsCctv(cam);
    setSelectedId(null);   // 모니터링 카메라 선택 해제
  }, []);

  // ITS CCTV 탭 변경 시 지도 마커 목록 갱신
  const handleItsCctvListChange = useCallback((list) => {
    setItsCctvList(list);
  }, []);

  // ── 카메라 선택 ───────────────────────────────────────────
  const handleSelect = (camera_id) => {
    setSelectedId(camera_id);
    setSelectedItsCctv(null);  // 모니터링 카메라 선택 시 ITS 보기 해제
    emitSelectCamera(camera_id);
  };

  // 첫 카메라 수신 시 자동 선택
  useEffect(() => {
    if (!selectedId && Object.keys(cameras).length > 0) {
      setSelectedId(Object.keys(cameras)[0]);
    }
  }, [cameras, selectedId]);

  // ── 역주행 경보 해제 ──────────────────────────────────────
  const handleDismissWrongway = useCallback((eventId) => {
    stopWrongwayAlarm();
    resolveEvent(eventId);
    setUnresolvedCounts_wrongway(); // 카운트 감소는 resolveEvent로 처리됨
  }, [stopWrongwayAlarm, resolveEvent]);

  // unresolvedCounts.wrongway 감소 처리
  const [wrongwayAdj, setWrongwayAdj] = useState(0);
  const handleDismissWrongwayFull = useCallback((eventId) => {
    stopWrongwayAlarm();
    resolveEvent(eventId);
    setWrongwayAdj(v => v + 1);
  }, [stopWrongwayAlarm, resolveEvent]);

  const selectedData = selectedId ? cameras[selectedId] : null;

  const displayCounts = {
    congested: unresolvedCounts.congested,
    slow:      unresolvedCounts.slow,
    wrongway:  Math.max(0, unresolvedCounts.wrongway - wrongwayAdj),
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', background: '#020617', overflow: 'hidden',
      // CONGESTED 감지 시 테두리 빨강 flash
      boxShadow: flashActive ? 'inset 0 0 0 3px #ef4444' : 'inset 0 0 0 3px transparent',
      transition: 'box-shadow 0.3s ease',
    }}>

      {/* ── 헤더 바 ─────────────────────────────────────────── */}
      <div style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontWeight: 700, fontSize: '14px', color: '#fff' }}>
            🚦 교통 정체 흐름
          </span>
          <LiveDot connected={connected} />
          <span style={{ fontSize: '12px', color: '#475569' }}><Clock /></span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '12px' }}>
            <span style={{ color: '#ef4444' }}>🔴 {displayCounts.congested}건</span>
            <span style={{ color: '#eab308' }}>🟡 {displayCounts.slow}건</span>
            <span style={{ color: '#f97316' }}>⚠️ {displayCounts.wrongway}건</span>
          </div>
          <button
            onClick={() => setSoundOn(v => !v)}
            style={{
              background: 'transparent',
              border: `1px solid ${soundOn ? '#22c55e55' : '#33415588'}`,
              color: soundOn ? '#22c55e' : '#475569',
              padding: '3px 10px', borderRadius: '6px',
              fontSize: '12px', cursor: 'pointer',
            }}
          >
            {soundOn ? '🔔 ON' : '🔕 OFF'}
          </button>
        </div>
      </div>

      {/* ── 바디 (3단 레이아웃) ──────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', gap: '8px', padding: '8px', minHeight: 0 }}>

        {/* LEFT — 구간 목록 */}
        <div style={{ ...styles.panel, width: isMobile ? '150px' : '200px', flexShrink: 0 }}>
          <SectionList
            host={host}
            cameras={cameras}
            selectedId={selectedId}
            onSelect={handleSelect}
            onViewItsCctv={handleViewItsCctv}
            onCctvListChange={handleItsCctvListChange}
          />
        </div>

        {/* CENTER — 지도 + CCTV */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <MonitoringMap
              host={host}
              cameras={cameras}
              selectedId={selectedId}
              onSelect={handleSelect}
              onViewItsCctv={handleViewItsCctv}
              itsCctvList={itsCctvList}
              selectedItsId={selectedItsCctv?.camera_id}
            />
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <CctvPlayer
              host={host}
              cameraId={selectedId}
              cameraData={selectedData}
              itsCctv={selectedItsCctv}
            />
          </div>
        </div>

        {/* RIGHT — 지표 패널 + 대응 패널 자리 */}
        <div style={{ width: isMobile ? '190px' : '250px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ flex: 1, minHeight: 0 }}>
            <MetricsPanel data={selectedData} />
          </div>
          <div style={{ height: '220px', flexShrink: 0 }}>
            <ActionPanel host={host} cameraId={selectedId} cameraData={selectedData} />
          </div>
        </div>
      </div>

      {/* ── 이벤트 로그 (하단) ──────────────────────────────── */}
      <div style={{
        height: '130px', margin: '0 8px 8px',
        background: '#0f172a', borderRadius: '12px',
        border: '1px solid #1e293b',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden', flexShrink: 0,
      }}>
        <EventLog
          eventLogs={eventLogs}
          onSelectCamera={handleSelect}
          onDismissWrongway={handleDismissWrongwayFull}
        />
      </div>

      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

const styles = {
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '10px 14px', background: '#0f172a',
    borderBottom: '1px solid #1e293b', flexShrink: 0,
  },
  panel: {
    background: '#0f172a', borderRadius: '12px',
    border: '1px solid #1e293b', overflow: 'hidden',
    display: 'flex', flexDirection: 'column',
  },
  placeholder: {
    background: '#0f172a', borderRadius: '12px',
    border: '1px dashed #1e293b',
    display: 'flex', alignItems: 'center',
    justifyContent: 'center', flexDirection: 'column', gap: '8px',
  },
  placeholderText: { fontSize: '12px', color: '#1e293b' },
};
