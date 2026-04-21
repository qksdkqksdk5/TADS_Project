/* eslint-disable */
// ✅ 파일 위치: src/modules/traffic/hooks/useMapMarkers.js

import { useRef } from 'react';

export function useMapMarkers(mapRef) {
  const markersRef = useRef({});

  const clearMarkersRef = () => {
    markersRef.current = {};
  };

  const createMarker = (alert, resolveEmergency) => {
    // window.kakao 체크 및 지도 존재 확인
    if (!mapRef.current || !window.kakao) return;
    
    // 이미 이 지도 인스턴스에 마커가 있다면 중복 생성 방지
    if (markersRef.current[alert.id]) return;

    const coord = new window.kakao.maps.LatLng(alert.lat, alert.lng);
    const fnName = `resolveFromMap_${alert.id}`;
    
    // resolveEmergency가 넘어왔는지 확인 후 할당
    window[fnName] = () => {
      if (typeof resolveEmergency === 'function') {
        resolveEmergency(alert.id, alert.type, alert.address, alert.origin);
      }
    };

    const content = `
      <div style="position: relative; bottom: 50px; background: white; border-radius: 12px; border: 2px solid #ff4d4f; box-shadow: 0 4px 12px rgba(0,0,0,0.2); padding: 10px; min-width: 140px;">
        <div style="display:flex; flex-direction:column; align-items:center; gap:5px;">
          <span style="font-size:12px; font-weight:800; color:#ff4d4f; white-space:nowrap;">⚠️ ${alert.type}</span>
          <span style="font-size:11px; color:#666; text-align:center; display:block; width:100%; word-break:break-all;">
            ${alert.address || "주소 확인 중..."}
          </span>
          <button onclick="window['${fnName}']()"
                  style="background:#ff4d4f; color:white; border:none; padding:4px 10px; border-radius:6px; font-size:11px; cursor:pointer; font-weight:bold; margin-top:5px;">
            조치 완료
          </button>
        </div>
        <div style="position: absolute; bottom: -10px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 8px solid transparent; border-right: 8px solid transparent; border-top: 10px solid #ff4d4f;"></div>
      </div>`;

    const overlay = new window.kakao.maps.CustomOverlay({
      content, map: mapRef.current, position: coord, yAnchor: 1
    });

    markersRef.current[alert.id] = overlay;
  };

  const removeMarker = (alertId) => {
    if (markersRef.current[alertId]) {
      markersRef.current[alertId].setMap(null);
      delete markersRef.current[alertId];
      delete window[`resolveFromMap_${alertId}`];  // ✅ 전역 함수도 함께 정리
    }
  };

  return { markersRef, createMarker, removeMarker, clearMarkersRef };
}