/* eslint-disable */
import { loadKakaoMapSDK } from '../loadKakaoMap';
import React, { useEffect } from 'react';

// 🚩 수정 포인트 1: pendingAlerts와 createMarker를 props에 추가했습니다.
const MapPanel = ({ 
  activeTab, isEmergency, mapRef, onHide, 
  pendingAlerts, createMarker, resolveEmergency, clearMarkersRef 
}) => {
  useEffect(() => {
    const initMap = () => {
      const container = document.getElementById('map');
      if (!container) return;

      // 초기 좌표 설정
      const defaultLat = 37.5665;
      const defaultLng = 126.9780;

      const options = {
        center: new window.kakao.maps.LatLng(defaultLat, defaultLng),
        level: 4
      };
      
      const mapInstance = new window.kakao.maps.Map(container, options);
      mapRef.current = mapInstance;

      // 🚩 수정 포인트 2: 새 지도가 떴으니 기존 마커 '기록'을 비웁니다.
      if (typeof clearMarkersRef === 'function') clearMarkersRef();

      if (pendingAlerts && pendingAlerts.length > 0) {
        // 🚩 수정 포인트 3: 지도가 안정화될 시간을 줍니다 (0.2초)
        setTimeout(() => {
          pendingAlerts.forEach(alert => {
            if (typeof createMarker === 'function') {
              // 🚩 수정 포인트 4: 두 번째 인자로 resolveEmergency를 반드시 전달!
              createMarker(alert, resolveEmergency);
            }
          });

          const latest = pendingAlerts[0];
          if (isEmergency && latest.lat) {
            mapInstance.setCenter(new window.kakao.maps.LatLng(latest.lat, latest.lng));
          }
        }, 200);
      }
      mapInstance.relayout();
    };

    loadKakaoMapSDK().then(initMap);

    // 긴급 상황 발생 시 레이아웃 재정렬
    if (isEmergency && mapRef.current) {
      setTimeout(() => {
        if (mapRef.current) mapRef.current.relayout();
      }, 500);
    }

    const handleResize = () => {
      if (mapRef.current) mapRef.current.relayout();
    };
    window.addEventListener('resize', handleResize);

    const animationInterval = setInterval(() => {
      if (mapRef.current) mapRef.current.relayout();
    }, 100);

    const stopTimer = setTimeout(() => { 
      clearInterval(animationInterval); 
    }, 1000);

    return () => {
      window.removeEventListener('resize', handleResize);
      clearInterval(animationInterval);
      clearTimeout(stopTimer);
    };
  }, [activeTab, isEmergency, pendingAlerts]); // pendingAlerts 추가하여 데이터 변경 시 대응

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{
        padding: '12px 20px',
        background: isEmergency ? '#7f1d1d' : '#111827',
        borderBottom: '1px solid #1e293b',
        color: '#fff', fontSize: '14px', fontWeight: 'bold',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        flexShrink: 0, transition: 'background 0.3s ease'
      }}>
        <span>🗺️ 현장 지도 {isEmergency && "(긴급 상황 발생)"}</span>
        {isEmergency && (
          <button onClick={onHide} style={{
            background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.3)',
            color: '#fff', fontSize: '11px', padding: '2px 8px', borderRadius: '4px', cursor: 'pointer'
          }}>
            ✕ 지도 숨기기
          </button>
        )}
      </div>
      <div id="map" style={{ width: '100%', flex: 1, minHeight: '300px', background: '#0f172a' }} />
    </div>
  );
};

export default MapPanel;