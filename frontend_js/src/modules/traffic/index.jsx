/* eslint-disable */
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import VideoPanel   from './components/VideoPanel';
import MapPanel     from './components/MapPanel';
import ControlPanel from './components/ControlPanel';
import { fetchCctvUrl, startSimulation, stopSimulation, stopDetection } from './api';

const getOrigin = (host) => {
  if (host.startsWith('http')) return host;
  const outsideHost = 'itsras.illit.kr';
  return host === outsideHost ? `https://${host}` : `http://${host}:5000`;
  
};

export default function TrafficModule({ socket, user, activeTab, isMobile, host,
  isEmergency, pendingAlerts, logs, mapRef, resolveEmergency, resolveAllAlertsAction, moveToAlert,
  videoUrl, setVideoUrl, createMarker, clearMarkersRef }) {

  const navigate = useNavigate();
  const [cctvData, setCctvData] = useState([]);
  const [showMap, setShowMap]   = useState(true);
  const prevTabRef = useRef(activeTab);

  const loadCctvUrl = async () => {
    try {
      const response = await fetchCctvUrl(host);
      if (response.data.success) setCctvData(response.data.cctvData);
    } catch (err) { console.error("CCTV API 호출 실패:", err); }
  };

  useEffect(() => {
    if (activeTab === "webcam") {
      setTimeout(() => {
        setVideoUrl(`${getOrigin(host)}/api/video_feed?type=webcam&v=${Date.now()}`);
      }, 100);
    } else if (activeTab === "cctv") {
      setVideoUrl("");
      if (cctvData.length === 0) loadCctvUrl();
    }
  }, [activeTab, host]);

  useEffect(() => {
    const prevTab = prevTabRef.current;
    
    if (prevTab !== activeTab) {
      // 1. 시뮬레이션 탭을 완전히 벗어날 때만 시뮬레이션 중지
      if (prevTab === "sim" && activeTab !== "sim") {
        console.log("🛑 시뮬레이션 종료 (시뮬레이션 탭을 벗어남)");
        stopSimulation(host);
      }

      // 2. CCTV 관제 탭을 벗어날 때 (일반 분석기만 종료)
      if (prevTab === "cctv" && cctvData.length > 0) {
        console.log("🧹 실시간 분석 리소스 정리 (시뮬레이션 제외)");
        cctvData.forEach(item => {
          if (!item.name) return;
          
          // 핵심: 일반 분석(reverse, fire)만 중지 명령을 보냅니다.
          // 백엔드 stopDetection에서 명시적으로 일반 이름만 타겟팅해야 합니다.
          stopDetection(host, { name: item.name, type: 'reverse' }).catch(() => {});
          stopDetection(host, { name: item.name, type: 'fire' }).catch(() => {});
        });
      }
    }

    prevTabRef.current = activeTab;
  }, [activeTab, host, cctvData]);

  useEffect(() => {
    if (!mapRef.current) return;
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
  }, [activeTab, isEmergency, pendingAlerts.length]);

  const startSim = (type) => {
    startSimulation(host, type)
      .then(() => {
        // 본인은 직접 탭 이동 + 영상 세팅
        navigate(`/dashboard/sim`);
        const encodedType = encodeURIComponent(type);
        setTimeout(() => {
          setVideoUrl(`${getOrigin(host)}/api/video_feed?type=${encodedType}&v=${Date.now()}`);
        }, 500);
      })
      .catch(err => console.error("시뮬레이션 시작 실패:", err));
  };

  const resolveAllAlerts = () => {
    if (pendingAlerts.length === 0) return;
    resolveAllAlertsAction(pendingAlerts, activeTab === "sim");
  };

  const handleAlertClick = (alert) => {
    moveToAlert(alert);
    if (mapRef.current) {
      mapRef.current.setLevel(2, {
        anchor: new window.kakao.maps.LatLng(alert.lat, alert.lng),
        animate: true,
      });
    }
  };

  return (
    <div style={{
      display: 'flex',
      flex: 1,
      flexDirection: isMobile ? 'column' : 'row',
      gap: isMobile ? '10px' : '20px',
      minHeight: 0,
      animation: isEmergency ? 'emergency-bg 0.8s infinite' : 'none',
    }}>
      <style>{pulseAnimation}</style>

      <div style={{ flex: 3.2, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ ...panelWrapper, flex: 1, marginBottom: (isEmergency && showMap) ? (isMobile ? '10px' : '20px') : '0px', transition: 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)' }}>
          <VideoPanel videoUrl={videoUrl} activeTab={activeTab} cctvData={cctvData} host={host} user={user} loadCctvUrl={loadCctvUrl}/>
        </div>

        {isEmergency && !showMap && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '10px 0' }}>
            <button onClick={() => setShowMap(true)} style={reShowBtnStyle}>
              📍 지도 펼치기 (위치 확인)
            </button>
          </div>
        )}

        <div style={{
          ...panelWrapper,
          maxHeight: (isEmergency && showMap) ? (isMobile ? '400px' : '600px') : '0px',
          opacity: (isEmergency && showMap) ? 1 : 0,
          flex: (isEmergency && showMap) ? 1.5 : 0,
          overflow: 'hidden',
          transition: 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)',
          borderWidth: (isEmergency && showMap) ? '1px' : '0px',
          borderStyle: 'solid',
          borderColor: (isEmergency && showMap) ? '#1e293b' : 'transparent',
        }}>
          <MapPanel activeTab={activeTab} isEmergency={isEmergency} mapRef={mapRef} onHide={() => setShowMap(false)} pendingAlerts={pendingAlerts} createMarker={createMarker} resolveEmergency={resolveEmergency} clearMarkersRef={clearMarkersRef} />
        </div>
      </div>

      <div style={{ flex: 0.8, display: 'flex', flexDirection: 'column', gap: isMobile ? '10px' : '20px', minHeight: 0 }}>
        <div style={{ flex: 1, minHeight: isMobile ? '300px' : 0 }}>
          <ControlPanel activeTab={activeTab} startSim={startSim} logs={logs} />
        </div>

        <div style={{ ...alertListPanel, flex: 0.72, minHeight: isMobile ? '250px' : 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
            <h4 style={{ color: '#f87171', fontSize: '14px', margin: 0 }}>
              🚨 미조치 알림 ({pendingAlerts.length})
            </h4>
            {pendingAlerts.length > 0 && (
              <button onClick={resolveAllAlerts} style={resolveAllBtn}>전체 조치</button>
            )}
          </div>
          <div style={{ flex: 1, overflowY: 'auto', paddingRight: '5px' }}>
            {pendingAlerts.length === 0 ? (
              <div style={{ color: '#475569', fontSize: '12px', textAlign: 'center', padding: '10px' }}>
                현재 상황 없음
              </div>
            ) : (
              pendingAlerts.map(alert => (
                <div key={alert.id} style={miniAlertCard}>
                  <div onClick={() => handleAlertClick(alert)} style={{ flex: 1, cursor: 'pointer' }}>
                    <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#f87171' }}>{alert.type}</div>
                    <div style={{ fontSize: '11px', color: '#94a3b8' }}>{alert.address}</div>
                  </div>
                  <button
                    onClick={() => resolveEmergency(alert.id, alert.type, alert.address, alert.origin, user?.name, activeTab === "sim")}
                    style={resolveBtn}
                  >
                    조치
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const pulseAnimation = `@keyframes emergency-bg { 0%, 100% { background-color: transparent; } 50% { background-color: #1e0000; } }`;
const panelWrapper   = { background: '#0f172a', borderRadius: '12px', border: '1px solid #1e293b', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' };
const alertListPanel = { background: '#0f172a', padding: '15px', borderRadius: '12px', border: '1px solid #451a1a', boxSizing: 'border-box' };
const miniAlertCard  = { display: 'flex', alignItems: 'center', padding: '10px', background: '#1e293b', borderRadius: '8px', border: '1px solid #334155', marginBottom: '8px' };
const resolveBtn     = { background: '#2563eb', color: 'white', border: 'none', padding: '5px 12px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold', cursor: 'pointer' };
const resolveAllBtn  = { background: 'transparent', color: '#f87171', border: '1px solid #f87171', padding: '3px 8px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer' };
const reShowBtnStyle = { background: '#1e293b', color: '#38bdf8', border: '1px solid #38bdf8', padding: '8px 16px', borderRadius: '20px', fontSize: '13px', fontWeight: 'bold', cursor: 'pointer', boxShadow: '0 0 10px rgba(56, 189, 248, 0.2)', transition: 'all 0.2s' };