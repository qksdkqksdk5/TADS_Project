/* eslint-disable */
import { useState, useEffect } from 'react';
import { useAnomalyDetection } from './hooks/useAnomalyDetection';
import VideoPanel    from './components/VideoPanel';
import MapPanel      from './components/MapPanel';
import ControlPanel  from './components/ControlPanel';
import Sidebar       from '../../shared/components/Sidebar';
import StatsModule   from '../stats';

// ✅ 새 탭 import
import PlateModule       from '../plate';
import MonitoringModule  from '../monitoring';
import TunnelModule      from '../tunnel';
import RaspiModule       from '../raspi';

import { fetchCctvUrl, startSimulation } from './api';

function TrafficDashboard({ socket, user, setUser, onLogout }) {
  const [activeTab, setActiveTab] = useState("cctv");
  const [videoUrl, setVideoUrl]   = useState("");
  const [isMobile, setIsMobile]   = useState(window.innerWidth < 1024);
  const [cctvData, setCctvData]   = useState([]);
  const [showMap, setShowMap]     = useState(true);

  const host = window.location.hostname;

  const loadCctvUrl = async () => {
    try {
      const response = await fetchCctvUrl(host);
      if (response.data.success) setCctvData(response.data.cctvData);
    } catch (err) { console.error("CCTV API 호출 실패:", err); }
  };

  const { isEmergency, pendingAlerts, logs, mapRef,
          resolveEmergency, resolveAllAlertsAction, moveToAlert } =
    useAnomalyDetection(socket, activeTab, setActiveTab, setVideoUrl, host, user?.name);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 1024);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // ✅ 독립 모듈 탭 목록 (관제 영상/지도 불필요한 탭들)
  const MODULE_TABS = ["stats", "plate", "monitoring", "tunnel", "raspi"];
  const isModuleTab = MODULE_TABS.includes(activeTab);

  useEffect(() => {
    if (!isModuleTab && mapRef.current) {
      mapRef.current.relayout();
      if (isEmergency && pendingAlerts.length > 0) setShowMap(true);
      const timer = setTimeout(() => {
        mapRef.current.relayout();
        if (isEmergency && pendingAlerts.length > 0) {
          const latestAlert = pendingAlerts[0];
          mapRef.current.panTo(new window.kakao.maps.LatLng(latestAlert.lat, latestAlert.lng));
        }
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [activeTab, isEmergency, pendingAlerts.length]);

  if (!user) return null;

  const handleLogout = () => {
    if (onLogout){onLogout(); navigate('/');}
    else { sessionStorage.removeItem('user'); setUser(null); if (socket) {socket.disconnect();} window.location.href = "/"; }
  };

  useEffect(() => {
    if (activeTab === "cctv") loadCctvUrl();
  }, []);

  const handleTabChange = (tab) => {
    setVideoUrl("");
    setActiveTab(tab);
    if (tab === "webcam" || tab === "sim") {
      setTimeout(() => setVideoUrl(`http://${host}:5000/api/video_feed?type=${tab}&v=${Date.now()}`), 100);
    } else if (tab === "cctv") {
      loadCctvUrl();
    }
  };

  const startSim = (type) => {
    startSimulation(host, type).catch(err => console.error("시뮬레이션 시작 실패:", err));
  };

  const resolveAllAlerts = () => {
    if (pendingAlerts.length === 0) return;
    resolveAllAlertsAction(pendingAlerts, activeTab === "sim");
  };

  const handleAlertClick = (alert) => {
    moveToAlert(alert);
    if (mapRef.current) {
      mapRef.current.setLevel(2, { anchor: new window.kakao.maps.LatLng(alert.lat, alert.lng), animate: true });
    }
  };

  return (
    <div style={{
      ...containerStyle,
      flexDirection: isMobile ? 'column' : 'row',
      height: isMobile ? 'auto' : '100vh',
      overflow: isMobile ? 'visible' : 'hidden',
      animation: isEmergency ? 'emergency-bg 0.8s infinite' : 'none'
    }}>
      <style>{pulseAnimation + (isMobile ? "" : hideScrollbar)}</style>

      <Sidebar activeTab={activeTab} onTabChange={handleTabChange} user={user} onLogout={handleLogout} isMobile={isMobile} />

      <main style={{ ...mainWrapper, height: isMobile ? 'auto' : '100vh', padding: isMobile ? '10px' : '15px', display: 'flex', flexDirection: 'column', overflow: isMobile ? 'visible' : 'hidden' }}>
        <div style={{ ...gridContainer, flexDirection: isMobile ? 'column' : 'row', flex: 1, minHeight: 0, gap: isMobile ? '10px' : '20px' }}>

          {/* ✅ 조건부 렌더링으로 변경 — 해당 탭 아닐 때 완전히 언마운트되어 폴링 자동 정지 */}
          {activeTab === "stats" && (
            <div style={{ display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' }}>
              <StatsModule isMobile={isMobile} host={host} />
            </div>
          )}

          {activeTab === "plate" && (
            <div style={{ display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' }}>
              <PlateModule isMobile={isMobile} host={host} />
            </div>
          )}

          {activeTab === "monitoring" && (
            <div style={{ display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' }}>
              <MonitoringModule isMobile={isMobile} host={host} />
            </div>
          )}

          {activeTab === "tunnel" && (
            <div style={{ display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' }}>
              <TunnelModule isMobile={isMobile} host={host} />
            </div>
          )}

          {activeTab === "raspi" && (
            <div style={{ display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' }}>
              <RaspiModule isMobile={isMobile} host={host} />
            </div>
          )}

          {/* 관제/시뮬레이션 탭 영역 */}
          <div style={{ display: !isModuleTab ? 'flex' : 'none', flex: 1, flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? '10px' : '20px', minHeight: 0 }}>
            <div style={{ flex: 3.2, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <div style={{ ...panelWrapper, flex: 1, marginBottom: (isEmergency && showMap) ? (isMobile ? '10px' : '20px') : '0px', transition: 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)' }}>
                <VideoPanel videoUrl={videoUrl} activeTab={activeTab} cctvData={cctvData} host={host} user={user} />
              </div>
              {isEmergency && !showMap && (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '10px 0' }}>
                  <button onClick={() => setShowMap(true)} style={reShowBtnStyle}>📍 지도 펼치기 (위치 확인)</button>
                </div>
              )}
              <div style={{ ...panelWrapper, maxHeight: (isEmergency && showMap) ? (isMobile ? '400px' : '600px') : '0px', opacity: (isEmergency && showMap) ? 1 : 0, flex: (isEmergency && showMap) ? 1.5 : 0, overflow: 'hidden', transition: 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)', border: (isEmergency && showMap) ? '1px solid #1e293b' : '0px solid transparent' }}>
                <MapPanel activeTab={activeTab} isEmergency={isEmergency} mapRef={mapRef} onHide={() => setShowMap(false)} />
              </div>
            </div>
            <div style={{ flex: 0.8, display: 'flex', flexDirection: 'column', gap: isMobile ? '10px' : '20px', minHeight: 0 }}>
              <div style={{ flex: 1, minHeight: isMobile ? '300px' : 0 }}>
                <ControlPanel activeTab={activeTab} startSim={startSim} logs={logs} />
              </div>
              <div style={{ ...alertListPanel, flex: 0.72, minHeight: isMobile ? '250px' : 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
                  <h4 style={{ color: '#f87171', fontSize: '14px', margin: 0 }}>🚨 미조치 알림 ({pendingAlerts.length})</h4>
                  {pendingAlerts.length > 0 && <button onClick={resolveAllAlerts} style={resolveAllBtn}>전체 조치</button>}
                </div>
                <div style={{ flex: 1, overflowY: 'auto', paddingRight: '5px' }}>
                  {pendingAlerts.length === 0 ? (
                    <div style={{ color: '#475569', fontSize: '12px', textAlign: 'center', padding: '10px' }}>현재 상황 없음</div>
                  ) : (
                    pendingAlerts.map(alert => (
                      <div key={alert.id} style={miniAlertCard}>
                        <div onClick={() => handleAlertClick(alert)} style={{ flex: 1, cursor: 'pointer' }}>
                          <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#f87171' }}>{alert.type}</div>
                          <div style={{ fontSize: '11px', color: '#94a3b8' }}>{alert.address}</div>
                        </div>
                        <button onClick={() => resolveEmergency(alert.id, alert.type, alert.address, alert.origin, user?.name, activeTab === "sim")} style={resolveBtn}>조치</button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}

const pulseAnimation = `@keyframes emergency-bg { 0%, 100% { background-color: #020617; } 50% { background-color: #1e0000; } }`;
const hideScrollbar  = `*::-webkit-scrollbar { display: none !important; } * { -ms-overflow-style: none !important; scrollbar-width: none !important; }`;
const containerStyle  = { display: 'flex', background: '#020617', color: '#fff', width: '100vw', boxSizing: 'border-box' };
const mainWrapper     = { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, boxSizing: 'border-box' };
const gridContainer   = { display: 'flex' };
const panelWrapper    = { background: '#0f172a', borderRadius: '12px', border: '1px solid #1e293b', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' };
const alertListPanel  = { background: '#0f172a', padding: '15px', borderRadius: '12px', border: '1px solid #451a1a', boxSizing: 'border-box' };
const miniAlertCard   = { display: 'flex', alignItems: 'center', padding: '10px', background: '#1e293b', borderRadius: '8px', border: '1px solid #334155', marginBottom: '8px' };
const resolveBtn      = { background: '#2563eb', color: 'white', border: 'none', padding: '5px 12px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold', cursor: 'pointer' };
const resolveAllBtn   = { background: 'transparent', color: '#f87171', border: '1px solid #f87171', padding: '3px 8px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer' };
const reShowBtnStyle  = { background: '#1e293b', color: '#38bdf8', border: '1px solid #38bdf8', padding: '8px 16px', borderRadius: '20px', fontSize: '13px', fontWeight: 'bold', cursor: 'pointer', boxShadow: '0 0 10px rgba(56, 189, 248, 0.2)', transition: 'all 0.2s' };

export default TrafficDashboard;