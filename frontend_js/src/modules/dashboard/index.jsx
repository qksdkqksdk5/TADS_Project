/* eslint-disable */
// src/modules/dashboard/index.jsx
// 역할: 레이아웃(사이드바 + 메인), 탭 라우팅, 각 모듈 렌더링
// CCTV 관련 로직은 traffic/index.jsx가 담당

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Sidebar      from '../../shared/components/Sidebar';
import TrafficModule  from '../traffic';
import PlateModule    from '../plate';
import MonitoringModule from '../monitoring';
import TunnelModule   from '../tunnel';
import RaspiModule    from '../raspi';
import StatsModule    from '../stats';

const VALID_TABS = ["cctv", "webcam", "sim", "stats", "plate", "monitoring", "tunnel", "raspi"];
const MODULE_TABS = ["stats", "plate", "monitoring", "tunnel", "raspi"];

export default function Dashboard({ socket, user, setUser, onLogout }) {
  const { tab } = useParams();
  const navigate = useNavigate();

  const activeTab = VALID_TABS.includes(tab) ? tab : "cctv";
  const isModuleTab = MODULE_TABS.includes(activeTab);

  const [isMobile, setIsMobile] = useState(window.innerWidth < 1024);
  const host = window.location.hostname;

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

          {/* 각 모듈 탭 */}
          {activeTab === "stats" && (
            <div style={moduleWrapper}>
              <StatsModule isMobile={isMobile} host={host} />
            </div>
          )}
          {activeTab === "plate" && (
            <div style={moduleWrapper}>
              <PlateModule isMobile={isMobile} host={host} />
            </div>
          )}
          {activeTab === "monitoring" && (
            <div style={moduleWrapper}>
              <MonitoringModule isMobile={isMobile} host={host} />
            </div>
          )}
          {activeTab === "tunnel" && (
            <div style={moduleWrapper}>
              <TunnelModule isMobile={isMobile} host={host} />
            </div>
          )}
          {activeTab === "raspi" && (
            <div style={moduleWrapper}>
              <RaspiModule isMobile={isMobile} host={host} />
            </div>
          )}

          {/* CCTV/웹캠/시뮬 탭 — traffic 모듈이 담당 */}
          {!isModuleTab && (
            <TrafficModule
              socket={socket}
              user={user}
              activeTab={activeTab}
              isMobile={isMobile}
              host={host}
            />
          )}

        </div>
      </main>
    </div>
  );
}

const hideScrollbar  = `*::-webkit-scrollbar { display: none !important; } * { -ms-overflow-style: none !important; scrollbar-width: none !important; }`;
const containerStyle = { display: 'flex', background: '#020617', color: '#fff', width: '100vw', boxSizing: 'border-box' };
const mainWrapper    = { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, boxSizing: 'border-box' };
const moduleWrapper  = { display: 'flex', flex: 1, height: '100%', overflowY: 'auto', flexDirection: 'column' };