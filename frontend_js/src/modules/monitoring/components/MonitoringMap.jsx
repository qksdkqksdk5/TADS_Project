/* eslint-disable */
// src/modules/monitoring/components/MonitoringMap.jsx
import { useEffect, useRef, useState } from 'react';
import { loadKakaoMapSDK } from '../../traffic/loadKakaoMap';
import { fetchRoadGeo } from '../api';

// ── 상수 ──────────────────────────────────────────────────────
const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };
const LEVEL_LABEL = { SMOOTH: '원활',    SLOW: '서행',    CONGESTED: '정체',    JAM: '정체'    };
const ROAD_LINE_GRAY = '#334155';

function fmtDuration(sec) {
  if (!sec || sec <= 0) return '-';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ── 모니터링 카메라 마커 HTML ─────────────────────────────────
function makeMarkerContent(cam, isSelected) {
  const { camera_id, level, is_learning, relearning, learning_progress, learning_total } = cam;
  const showLearning = is_learning || relearning;
  const color  = showLearning ? '#6b7280' : (LEVEL_COLOR[level] || '#6b7280');
  const emoji  = showLearning ? '⟳'
               : (level === 'CONGESTED' || level === 'JAM') ? '🔴'
               : level === 'SLOW'      ? '🟡'
               : '🟢';
  const border  = isSelected ? '3px solid #38bdf8' : `2px solid ${color}`;
  const animCss = (!showLearning && level !== 'SMOOTH')
    ? 'animation: monPulse 1.2s ease infinite;'
    : showLearning ? 'animation: monSpin 1.6s linear infinite;' : '';

  const pct = (is_learning && learning_total)
    ? Math.min(Math.round((learning_progress / learning_total) * 100), 100) : 0;

  const badgeHtml = is_learning ? `
    <div style="margin-top:5px;background:rgba(2,6,23,0.85);border:1px solid #334155;
                border-radius:6px;padding:3px 6px;text-align:center;min-width:70px;">
      <div style="font-size:10px;color:#94a3b8;font-weight:600;margin-bottom:3px;">학습 중 ${pct}%</div>
      <div style="background:#1e293b;border-radius:3px;height:3px;overflow:hidden;">
        <div style="height:100%;width:${pct}%;background:#38bdf8;border-radius:3px;"></div>
      </div>
    </div>` : relearning ? `
    <div style="margin-top:5px;background:rgba(2,6,23,0.85);border:1px solid #431407;
                border-radius:6px;padding:3px 8px;text-align:center;">
      <div style="font-size:10px;color:#f97316;font-weight:600;">재보정 중...</div>
    </div>` : '';

  return `<div onclick="window.__monMapSelect('${camera_id}')"
    style="cursor:pointer;display:flex;flex-direction:column;align-items:center;" title="${camera_id}">
    <div style="background:#0f172a;border:${border};border-radius:50%;
                width:38px;height:38px;display:flex;align-items:center;justify-content:center;
                font-size:17px;box-shadow:0 2px 10px rgba(0,0,0,0.6);${animCss}transition:border 0.25s;">
      ${emoji}
    </div>${badgeHtml}
  </div>`;
}

// ── ITS CCTV 마커 HTML (보기 전용 — 파란 작은 점) ─────────────
function makeItsMarkerContent(cam, isSelected) {
  const border = isSelected ? '3px solid #38bdf8' : '2px solid #3b82f6';
  return `<div onclick="window.__monItsSelect('${encodeURIComponent(JSON.stringify(cam))}')"
    style="cursor:pointer;display:flex;flex-direction:column;align-items:center;" title="${cam.name}">
    <div style="background:#0c1a3a;border:${border};border-radius:50%;
                width:22px;height:22px;display:flex;align-items:center;justify-content:center;
                font-size:11px;box-shadow:0 2px 6px rgba(0,0,0,0.5);">
      📷
    </div>
  </div>`;
}

// ── 모니터링 팝업 HTML ────────────────────────────────────────
function makePopupContent(cam) {
  const { camera_id, level, is_learning, relearning, jam_score, duration_sec, location } = cam;
  const showLearning = is_learning || relearning;
  const color      = showLearning ? '#6b7280' : (LEVEL_COLOR[level] || '#6b7280');
  const levelLabel = showLearning
    ? (is_learning ? '학습 중' : '재보정 중') : (LEVEL_LABEL[level] || '-');

  const metricsHtml = !showLearning ? `
    <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
      <span style="font-size:11px;color:#64748b;">정체 지수</span>
      <span style="font-size:11px;font-weight:700;color:#e2e8f0;">${(jam_score ?? 0).toFixed(2)}</span>
    </div>
    <div style="display:flex;justify-content:space-between;">
      <span style="font-size:11px;color:#64748b;">지속 시간</span>
      <span style="font-size:11px;color:#e2e8f0;">${level === 'SMOOTH' ? '-' : fmtDuration(duration_sec)}</span>
    </div>` : '';

  return `<div style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;
                       padding:12px 14px;min-width:150px;font-family:sans-serif;
                       box-shadow:0 4px 16px rgba(0,0,0,0.7);color:#e2e8f0;pointer-events:none;">
    <div style="font-size:13px;font-weight:700;margin-bottom:6px;color:#fff;">${camera_id}</div>
    ${location ? `<div style="font-size:11px;color:#64748b;margin-bottom:8px;">${location}</div>` : ''}
    <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
      <span style="font-size:11px;color:#64748b;">레벨</span>
      <span style="font-size:11px;font-weight:700;color:${color};">${levelLabel}</span>
    </div>${metricsHtml}
  </div>`;
}

// ── 도로 선형 색상 계산 ───────────────────────────────────────
/**
 * GeoJSON의 각 LineString way를 카메라 위치로 분할하여 색상 폴리라인으로 반환.
 * 각 분절(segment)마다 가장 가까운 MonitoringDetector 카메라의 level로 색상을 부여한다.
 */
function buildColoredSegments(features, cameras) {
  if (!features || features.length === 0) return [];

  const camList = Object.values(cameras).filter(c => c.lat && c.lng);

  // 좌표 간 거리 (간이 유클리드, 지도 스케일용)
  const dist2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;

  const colored = [];

  for (const feat of features) {
    const coords = feat.geometry?.coordinates;
    if (!coords || coords.length < 2) continue;

    if (camList.length === 0) {
      // 카메라 없으면 전체 회색
      colored.push({ coords, color: ROAD_LINE_GRAY, strokeWeight: 5 });
      continue;
    }

    // 각 좌표 점마다 가장 가까운 카메라 레벨 찾기
    const pointLevels = coords.map(([lng, lat]) => {
      let minD = Infinity, nearest = null;
      for (const cam of camList) {
        const d = dist2([lng, lat], [cam.lng, cam.lat]);
        if (d < minD) { minD = d; nearest = cam; }
      }
      // 카메라가 300km^2 이내 (위도 기준 약 0.03도≒3.3km)에 없으면 회색
      return minD < 0.001 ? nearest?.level : null;
    });

    // 연속하는 같은 레벨끼리 묶어 세그먼트 생성
    let segStart = 0;
    for (let i = 1; i <= coords.length; i++) {
      const curLevel = i < coords.length ? pointLevels[i] : null;
      const prevLevel = pointLevels[i - 1];
      if (i === coords.length || curLevel !== prevLevel) {
        const segCoords = coords.slice(segStart, i);
        if (segCoords.length >= 2) {
          const color = LEVEL_COLOR[prevLevel] || ROAD_LINE_GRAY;
          colored.push({ coords: segCoords, color, strokeWeight: prevLevel ? 6 : 4 });
        }
        segStart = i;
      }
    }
  }

  return colored;
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function MonitoringMap({ host, cameras, selectedId, onSelect, onViewItsCctv, itsCctvList = [], selectedItsId }) {
  const mapRef        = useRef(null);
  const overlaysRef   = useRef({});     // 모니터링 카메라 마커
  const itsOverlayRef = useRef({});     // ITS CCTV 마커
  const popupRef      = useRef(null);
  const polylinesRef  = useRef([]);     // 도로 색상 폴리라인들
  const [roadGeo, setRoadGeo] = useState(null);

  // 전역 클릭 핸들러
  useEffect(() => {
    window.__monMapSelect  = (camera_id) => onSelect(camera_id);
    window.__monItsSelect  = (encoded) => {
      try { onViewItsCctv(JSON.parse(decodeURIComponent(encoded))); } catch {}
    };
    return () => { delete window.__monMapSelect; delete window.__monItsSelect; };
  }, [onSelect, onViewItsCctv]);

  // 도로 선형 GeoJSON 로드 (최초 1회)
  useEffect(() => {
    if (!host) return;
    fetchRoadGeo(host, 'gyeongbu')
      .then(res => setRoadGeo(res.data))
      .catch(() => {});
  }, [host]);

  // 지도 초기화 + CSS 주입 (마운트 1회)
  useEffect(() => {
    const styleEl = document.createElement('style');
    styleEl.id = 'mon-map-keyframes';
    styleEl.textContent = `
      @keyframes monPulse { 0%,100%{transform:scale(1);opacity:1;} 50%{transform:scale(1.25);opacity:0.7;} }
      @keyframes monSpin  { to{transform:rotate(360deg);} }
    `;
    if (!document.getElementById('mon-map-keyframes')) document.head.appendChild(styleEl);

    loadKakaoMapSDK().then(() => {
      const container = document.getElementById('monitoring-map');
      if (!container || mapRef.current) return;
      mapRef.current = new window.kakao.maps.Map(container, {
        center: new window.kakao.maps.LatLng(37.3, 127.3),  // 경부고속도로 중간 (수원 부근)
        level: 9,
      });
    });

    return () => {
      styleEl.remove();
      Object.values(overlaysRef.current).forEach(o => o.setMap(null));
      Object.values(itsOverlayRef.current).forEach(o => o.setMap(null));
      polylinesRef.current.forEach(p => p.setMap(null));
      popupRef.current?.setMap(null);
    };
  }, []);

  // ── 도로 폴리라인 그리기 ──────────────────────────────────
  useEffect(() => {
    if (!mapRef.current || !roadGeo) return;
    const map = mapRef.current;

    // 기존 폴리라인 제거
    polylinesRef.current.forEach(p => p.setMap(null));
    polylinesRef.current = [];

    const segments = buildColoredSegments(roadGeo.features, cameras);
    segments.forEach(({ coords, color, strokeWeight }) => {
      const path = coords.map(([lng, lat]) => new window.kakao.maps.LatLng(lat, lng));
      const poly = new window.kakao.maps.Polyline({
        path,
        strokeWeight,
        strokeColor:   color,
        strokeOpacity: 0.85,
        strokeStyle:   'solid',
      });
      poly.setMap(map);
      polylinesRef.current.push(poly);
    });
  }, [roadGeo, cameras]);

  // ── 모니터링 카메라 마커 갱신 ────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    Object.values(cameras).forEach(cam => {
      const { camera_id, lat, lng } = cam;
      if (!lat || !lng) return;
      const content = makeMarkerContent(cam, camera_id === selectedId);
      if (overlaysRef.current[camera_id]) {
        overlaysRef.current[camera_id].setContent(content);
      } else {
        const overlay = new window.kakao.maps.CustomOverlay({
          position: new window.kakao.maps.LatLng(lat, lng),
          content, yAnchor: 0.5, zIndex: 5,
        });
        overlay.setMap(map);
        overlaysRef.current[camera_id] = overlay;
      }
    });

    Object.keys(overlaysRef.current).forEach(id => {
      if (!cameras[id]) {
        overlaysRef.current[id].setMap(null);
        delete overlaysRef.current[id];
      }
    });
  }, [cameras, selectedId]);

  // ── ITS CCTV 마커 갱신 ───────────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    // 더 이상 없는 마커 제거
    const newIds = new Set(itsCctvList.map(c => c.camera_id));
    Object.keys(itsOverlayRef.current).forEach(id => {
      if (!newIds.has(id)) {
        itsOverlayRef.current[id].setMap(null);
        delete itsOverlayRef.current[id];
      }
    });

    itsCctvList.forEach(cam => {
      const { camera_id, lat, lng } = cam;
      if (!lat || !lng) return;
      const isSelected = cam.camera_id === selectedItsId;
      const content = makeItsMarkerContent(cam, isSelected);
      if (itsOverlayRef.current[camera_id]) {
        itsOverlayRef.current[camera_id].setContent(content);
      } else {
        const overlay = new window.kakao.maps.CustomOverlay({
          position: new window.kakao.maps.LatLng(lat, lng),
          content, yAnchor: 0.5, zIndex: 3,
        });
        overlay.setMap(map);
        itsOverlayRef.current[camera_id] = overlay;
      }
    });
  }, [itsCctvList, selectedItsId]);

  // ── 선택 카메라 팝업 + 지도 이동 ─────────────────────────
  useEffect(() => {
    if (!mapRef.current) return;
    popupRef.current?.setMap(null);
    popupRef.current = null;

    if (!selectedId || !cameras[selectedId]) return;
    const cam = cameras[selectedId];
    if (!cam.lat || !cam.lng) return;

    const popup = new window.kakao.maps.CustomOverlay({
      position: new window.kakao.maps.LatLng(cam.lat, cam.lng),
      content: makePopupContent(cam),
      yAnchor: 1.7, zIndex: 10,
    });
    popup.setMap(mapRef.current);
    popupRef.current = popup;
    mapRef.current.panTo(new window.kakao.maps.LatLng(cam.lat, cam.lng));
  }, [selectedId, cameras]);

  return (
    <div style={{ height: '100%', position: 'relative', borderRadius: '12px', overflow: 'hidden' }}>
      <div id="monitoring-map" style={{ width: '100%', height: '100%', minHeight: '180px' }} />

      {/* 범례 */}
      <div style={{
        position: 'absolute', bottom: '10px', right: '10px',
        background: 'rgba(15,23,42,0.85)', border: '1px solid #1e293b',
        borderRadius: '8px', padding: '6px 10px',
        fontSize: '10px', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '3px',
        pointerEvents: 'none',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ width: '18px', height: '3px', background: '#22c55e', borderRadius: '2px', display: 'inline-block' }} />
          원활
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ width: '18px', height: '3px', background: '#eab308', borderRadius: '2px', display: 'inline-block' }} />
          서행
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ width: '18px', height: '3px', background: '#ef4444', borderRadius: '2px', display: 'inline-block' }} />
          정체
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <span style={{ width: '18px', height: '3px', background: ROAD_LINE_GRAY, borderRadius: '2px', display: 'inline-block' }} />
          미감시
        </div>
      </div>

      {Object.keys(cameras).length === 0 && itsCctvList.length === 0 && (
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none',
          background: 'rgba(2,6,23,0.55)',
          fontSize: '12px', color: '#334155', gap: '6px',
        }}>
          <span style={{ fontSize: '24px' }}>📡</span>
          구간을 선택해 모니터링을 시작하세요
        </div>
      )}
    </div>
  );
}
