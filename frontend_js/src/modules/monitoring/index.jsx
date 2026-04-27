/* eslint-disable */
// src/modules/monitoring/index.jsx
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useMonitoringSocket } from './hooks/useMonitoringSocket';
import { useSoundAlert }       from './hooks/useSoundAlert';
import SectionList   from './components/SectionList';
import MetricsPanel  from './components/MetricsPanel';
import MonitoringMap from './components/MonitoringMap';
import CctvPlayer    from './components/CctvPlayer';
import EventLog      from './components/EventLog';
import ActionPanel   from './components/ActionPanel';
import { fetchItsCctv, restartCamera } from './api';

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

// ── 카메라 팝업 모달 ──────────────────────────────────────────
// onNavigate(dir): dir = -1(이전) | +1(다음) — 방향키 내비게이션 콜백
// currentIdx, total: 팝업 헤더에 표시할 "현재/전체" 카운터 (없으면 숨김)
function CameraPopup({ host, selectedId, selectedData, selectedItsCctv, onClose, onNavigate, currentIdx, total, streamFailures, onRestartCamera }) {
  // ESC → 닫기, ← → → 이전/다음 카메라
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape')      { onClose(); return; }
      // 텍스트 입력 중에는 방향키 내비게이션을 비활성화한다
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft')   { e.preventDefault(); onNavigate?.(-1); }
      if (e.key === 'ArrowRight')  { e.preventDefault(); onNavigate?.(1);  }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose, onNavigate]);

  const title = selectedItsCctv
    ? selectedItsCctv.name
    : (selectedData?.location || selectedId || '');

  // 카메라가 2개 이상일 때만 내비게이션 UI를 보여준다
  const showNav = total > 1;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(2,6,23,0.82)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width:  'min(1020px, 95vw)',
        height: 'min(580px, 90vh)',
        background: '#0f172a',
        borderRadius: '16px',
        border: '1px solid #1e293b',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
      }}>
        {/* 팝업 헤더 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '10px 14px', borderBottom: '1px solid #1e293b', flexShrink: 0,
          gap: '12px',
        }}>
          {/* 좌측: 카메라 이름 + 순번 + 방향키 힌트 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              📷 {title}
            </span>
            {/* 현재/전체 카운터 */}
            {showNav && (
              <span style={{ fontSize: '11px', color: '#475569', whiteSpace: 'nowrap', flexShrink: 0 }}>
                {currentIdx}/{total}
              </span>
            )}
            {/* 방향키 힌트 — 카메라 이름 바로 오른쪽 */}
            {showNav && (
              <span style={{ fontSize: '11px', color: '#334155', whiteSpace: 'nowrap', flexShrink: 0, userSelect: 'none' }}>
                ← → 전환
              </span>
            )}
          </div>

          {/* 우측: 레벨 기준 칩 + 닫기 버튼 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
            {/* 레벨 기준 칩 3개 — X 버튼 왼쪽 */}
            <span style={{ fontSize: '10px', color: '#334155', userSelect: 'none' }}>레벨 기준</span>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '2px 7px', background: '#22c55e12', border: '1px solid #22c55e33', borderRadius: '5px' }}>
              <span style={{ fontSize: '10px', color: '#22c55e', fontWeight: 700, lineHeight: 1.2 }}>원활</span>
              <span style={{ fontSize: '9px', color: '#4ade8077', lineHeight: 1.2 }}>&lt;0.25</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '2px 7px', background: '#eab30812', border: '1px solid #eab30833', borderRadius: '5px' }}>
              <span style={{ fontSize: '10px', color: '#eab308', fontWeight: 700, lineHeight: 1.2 }}>서행</span>
              <span style={{ fontSize: '9px', color: '#facc1577', lineHeight: 1.2 }}>0.25–</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '2px 7px', background: '#ef444412', border: '1px solid #ef444433', borderRadius: '5px' }}>
              <span style={{ fontSize: '10px', color: '#ef4444', fontWeight: 700, lineHeight: 1.2 }}>정체</span>
              <span style={{ fontSize: '9px', color: '#f8717177', lineHeight: 1.2 }}>≥0.60</span>
            </div>
            {/* 닫기 버튼 */}
            <button
              onClick={onClose}
              style={{
                background: 'transparent', border: '1px solid #1e293b',
                borderRadius: '6px', color: '#475569',
                width: '26px', height: '26px',
                fontSize: '13px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >✕</button>
          </div>
        </div>

        {/* 팝업 바디 */}
        <div style={{ flex: 1, display: 'flex', gap: '8px', padding: '8px', minHeight: 0 }}>
          {/* 영상 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <CctvPlayer
              host={host}
              cameraId={selectedId}
              cameraData={selectedData}
              itsCctv={selectedItsCctv}
              streamStatus={selectedId ? streamFailures?.[selectedId] : undefined}
              onRestartCamera={onRestartCamera}
            />
          </div>

          {/* 우측: 지표 + 대응 */}
          {!selectedItsCctv && (
            <div style={{ width: '230px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ flex: 1, minHeight: 0 }}>
                <MetricsPanel data={selectedData} />
              </div>
              <div style={{ height: '210px', flexShrink: 0 }}>
                <ActionPanel host={host} cameraId={selectedId} cameraData={selectedData} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function MonitoringModule({ host, isMobile }) {
  const [selectedId,      setSelectedId]      = useState(null);
  const [soundOn,         setSoundOn]         = useState(true);
  const [flashActive,     setFlashActive]     = useState(false);
  const [selectedItsCctv, setSelectedItsCctv] = useState(null);
  const [itsCctvList,     setItsCctvList]     = useState([]);
  const [popupOpen,       setPopupOpen]       = useState(false);
  // 현재 선택된 도로 키 — SectionList에서 탭 전환 시 갱신되고 MonitoringMap에 전달된다
  const [road,            setRoad]            = useState('gyeongbu');

  // ── 사운드 훅 ─────────────────────────────────────────────
  const {
    playAlert, playResolved,
    startWrongwayAlarm, stopWrongwayAlarm,
    startCongestionRepeat, stopCongestionRepeat,
  } = useSoundAlert(soundOn);

  // ── 소켓 훅 ───────────────────────────────────────────────
  const { cameras, eventLogs, unresolvedCounts, connected, emitSelectCamera, resolveEvent, removeCameras, serverRoadGeo, streamFailures } =
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

  // ── ITS CCTV 보기 핸들러 ──────────────────────────────────
  const handleViewItsCctv = useCallback((cam) => {
    setSelectedItsCctv(cam);
    setSelectedId(null);
    setPopupOpen(true);
  }, []);

  const handleItsCctvListChange = useCallback((list) => {
    setItsCctvList(list);
  }, []);

  // SectionList 탭 전환 시 호출 — road 상태를 갱신해 MonitoringMap이 새 도로를 그리도록 한다
  const handleRoadChange = useCallback((r) => setRoad(r), []);

  // ── 카메라 선택 → 팝업 열기 ──────────────────────────────
  const handleSelect = useCallback((camera_id) => {
    setSelectedId(camera_id);
    setSelectedItsCctv(null);
    setPopupOpen(true);
    emitSelectCamera(camera_id);
  }, [emitSelectCamera]);

  // ── 연결 실패 카메라 재시작 ───────────────────────────────────
  // "다시 시도" 버튼 클릭 시 호출 — 백엔드가 최신 ITS URL로 감지기를 재시작한다
  const handleRestartCamera = useCallback(async (camera_id) => {
    try {
      await restartCamera(host, camera_id);
    } catch (e) {
      console.error('[재시작 실패]', camera_id, e);
    }
  }, [host]);

  // ── 팝업 닫기 ─────────────────────────────────────────────
  const handleClosePopup = useCallback(() => {
    setPopupOpen(false);
    // 선택 상태는 유지 (지도 마커 하이라이트 등)
  }, []);

  // ── 선택 카메라가 제거되면 팝업 자동 닫기 ───────────────────
  useEffect(() => {
    if (selectedId && !cameras[selectedId]) {
      setSelectedId(null);
      setPopupOpen(false);
    }
  }, [cameras, selectedId]);

  // ── 이벤트 조치 처리 (조치 완료 / 조치 불필요) ──────────────
  // eventId: 처리할 이벤트 ID
  // reason: 'action'(조치 완료) | 'no_action'(조치 불필요)
  // 역주행 이벤트인 경우 경보음도 함께 중지한다
  const [wrongwayAdj, setWrongwayAdj] = useState(0);
  const handleDismiss = useCallback((eventId, reason) => {
    // 해당 이벤트가 역주행인지 확인 — 역주행이면 경보음 중지
    const target = eventLogs.find(ev => ev.id === eventId);
    if (target?.event_type === 'wrongway') {
      stopWrongwayAlarm();
      setWrongwayAdj(v => v + 1); // 역주행 미해결 카운트 보정
    }
    resolveEvent(eventId, reason); // 이벤트 상태를 해소됨으로 변경
  }, [eventLogs, stopWrongwayAlarm, resolveEvent]);

  // ── 방향키 카메라 전환 ────────────────────────────────────────
  // dir: -1(이전) | +1(다음)
  // ITS 모드이면 itsCctvList, 모니터링 모드이면 cameras 키 배열에서 순환한다.
  const navigateCamera = useCallback((dir) => {
    if (selectedItsCctv && itsCctvList.length > 0) {
      // ITS 카메라 목록에서 현재 위치를 찾아 dir 방향으로 순환
      const idx  = itsCctvList.findIndex(c => c.camera_id === selectedItsCctv.camera_id);
      if (idx === -1) return;
      const next = itsCctvList[(idx + dir + itsCctvList.length) % itsCctvList.length];
      setSelectedItsCctv(next);
    } else if (selectedId) {
      // 모니터링 카메라 목록에서 현재 위치를 찾아 dir 방향으로 순환
      const ids    = Object.keys(cameras);
      const idx    = ids.indexOf(selectedId);
      if (idx === -1) return;
      const nextId = ids[(idx + dir + ids.length) % ids.length];
      setSelectedId(nextId);
      emitSelectCamera(nextId);   // 서버에 카메라 선택 이벤트 전송
    }
  }, [selectedItsCctv, selectedId, itsCctvList, cameras, emitSelectCamera]);

  // ── 팝업 헤더용 현재/전체 카운터 ──────────────────────────────
  const navInfo = useMemo(() => {
    if (selectedItsCctv && itsCctvList.length > 0) {
      // ITS 모드: itsCctvList 내 현재 위치
      const idx = itsCctvList.findIndex(c => c.camera_id === selectedItsCctv.camera_id);
      return { current: idx + 1, total: itsCctvList.length };
    }
    if (selectedId) {
      // 모니터링 모드: cameras 키 배열 내 현재 위치
      const ids = Object.keys(cameras);
      const idx = ids.indexOf(selectedId);
      return { current: idx + 1, total: ids.length };
    }
    return null;
  }, [selectedItsCctv, selectedId, itsCctvList, cameras]);

  const selectedData = selectedId ? cameras[selectedId] : null;

  const displayCounts = {
    congested: unresolvedCounts.congested,
    slow:      unresolvedCounts.slow,
    wrongway:  Math.max(0, unresolvedCounts.wrongway - wrongwayAdj),
  };

  const showPopup = popupOpen && (selectedId || selectedItsCctv);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', background: '#020617', overflow: 'hidden',
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
            onRemoveCameras={removeCameras}
            onRoadChange={handleRoadChange}
          />
        </div>

        {/* CENTER — 지도 (전체 높이) */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
          <MonitoringMap
            host={host}
            cameras={cameras}
            selectedId={selectedId}
            onSelect={handleSelect}
            onViewItsCctv={handleViewItsCctv}
            itsCctvList={itsCctvList}
            selectedItsId={selectedItsCctv?.camera_id}
            serverRoadGeo={serverRoadGeo}
            road={road}
          />
        </div>

        {/* RIGHT — 이벤트 로그 */}
        <div style={{ ...styles.panel, width: isMobile ? '200px' : '280px', flexShrink: 0 }}>
          <EventLog
            eventLogs={eventLogs}
            onSelectCamera={handleSelect}
            onDismiss={handleDismiss}
          />
        </div>
      </div>

      {/* ── 카메라 팝업 ───────────────────────────────────────── */}
      {showPopup && (
        <CameraPopup
          host={host}
          selectedId={selectedId}
          selectedData={selectedData}
          selectedItsCctv={selectedItsCctv}
          onClose={handleClosePopup}
          onNavigate={navigateCamera}              // 방향키 ← → 내비게이션 콜백
          currentIdx={navInfo?.current}            // 현재 카메라 순번 (1-based)
          total={navInfo?.total}                   // 전체 카메라 수
          streamFailures={streamFailures}          // 카메라별 연결 실패 상태
          onRestartCamera={handleRestartCamera}    // "다시 시도" 버튼 클릭 시 호출
        />
      )}

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
};
