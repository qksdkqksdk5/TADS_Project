/* eslint-disable */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Sidebar      from '../../shared/components/Sidebar';
import ChatAssistant from '../../shared/components/chat/ChatAssistant';
import LLMDashboard from '../llm/LLMDashboard';
import TrafficModule  from '../traffic';
import PlateModule    from '../plate';
import MonitoringModule from '../monitoring';
import TunnelModule   from '../tunnel';
import RaspiModule    from '../raspi';
import StatsModule    from '../stats';
import { useAnomalyDetection } from '../traffic/hooks/useAnomalyDetection';

const VALID_TABS = ["cctv", "webcam", "sim", "stats", "plate", "monitoring", "tunnel", "raspi", "llm"];
const MODULE_TABS = ["stats", "plate", "monitoring", "tunnel", "raspi", "llm"];

export default function Dashboard({ socket, outsideSocket, user, setUser, onLogout }) {
  const { tab } = useParams();
  const navigate = useNavigate();

  const activeTab = VALID_TABS.includes(tab) ? tab : "cctv";
  const isModuleTab = MODULE_TABS.includes(activeTab);

  const [isMobile, setIsMobile] = useState(window.innerWidth < 1024);
  const [videoUrl, setVideoUrl] = useState("");
  const host = window.location.hostname;
  const outsideHost = 'itsras.illit.kr';

  const { isEmergency, pendingAlerts, logs, mapRef,
          resolveEmergency, resolveAllAlertsAction, moveToAlert, createMarker, clearMarkersRef } =
    useAnomalyDetection(
      outsideSocket,
      activeTab,
      (newTab) => navigate(`/dashboard/${newTab}`),
      setVideoUrl,
      outsideHost,
      user?.name
    );

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 1024);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  if (!user) return null;

  const handleTabChange = (newTab) => {
    navigate(`/dashboard/${newTab}`);
  };

  const handleLogout = () => {
    if (onLogout) { onLogout(); navigate('/'); }
    else {
      sessionStorage.removeItem('user');
      setUser(null);
      if (socket) socket.disconnect();
      window.location.href = "/";
    }
  };

  return (
    <div style={{
      ...containerStyle,
      flexDirection: isMobile ? 'column' : 'row',
      height: isMobile ? 'auto' : '100vh',
      overflow: isMobile ? 'visible' : 'hidden',
    }}>
      <style>{isMobile ? '' : hideScrollbar}</style>

      <Sidebar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        user={user}
        onLogout={handleLogout}
        isMobile={isMobile}
      />

      <main style={{
        ...mainWrapper,
        height: isMobile ? 'auto' : '100vh',
        padding: isMobile ? '10px' : '15px',
        overflow: isMobile ? 'visible' : 'hidden',
      }}>
        <div style={{
          display: 'flex',
          flexDirection: isMobile ? 'column' : 'row',
          flex: 1,
          minHeight: 0,
          gap: isMobile ? '10px' : '20px',
          height: '100%',
        }}>

          {activeTab === "stats" && (
            <div style={moduleWrapper}><StatsModule isMobile={isMobile} host={outsideHost} /></div>
          )}
          {activeTab === "plate" && (
            <div style={moduleWrapper}><PlateModule isMobile={isMobile} host={host} user={user} /></div>
          )}
          {activeTab === "monitoring" && (
            <div style={moduleWrapper}><MonitoringModule isMobile={isMobile} host={host} /></div>
          )}
          {activeTab === "tunnel" && (
            <div style={moduleWrapper}><TunnelModule isMobile={isMobile} host={host} /></div>
          )}
          {activeTab === "raspi" && (
            <div style={moduleWrapper}><RaspiModule isMobile={isMobile} host={outsideHost} socket={outsideSocket}/></div>
          )}
          {activeTab === "llm" && (
            <div style={moduleWrapper}>
              <LLMDashboard host={host} />
            </div>
          )}
          {!isModuleTab && (
            <TrafficModule
              socket={outsideSocket}
              user={user}
              activeTab={activeTab}
              isMobile={isMobile}
              host={outsideHost}
              isEmergency={isEmergency}
              pendingAlerts={pendingAlerts}
              logs={logs}
              mapRef={mapRef}
              resolveEmergency={resolveEmergency}
              resolveAllAlertsAction={resolveAllAlertsAction}
              moveToAlert={moveToAlert}
              videoUrl={videoUrl}
              setVideoUrl={setVideoUrl}
              createMarker={createMarker}
              clearMarkersRef={clearMarkersRef}
            />
          )}

        </div>
      </main>
      <ChatAssistant host={host} user={user} />
    </div>
  );
}

const hideScrollbar  = `*::-webkit-scrollbar { display: none !important; } * { -ms-overflow-style: none !important; scrollbar-width: none !important; }`;
const containerStyle = { display: 'flex', background: '#020617', color: '#fff', width: '100vw', boxSizing: 'border-box' };
const mainWrapper    = { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, boxSizing: 'border-box' };
const moduleWrapper  = { display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' };