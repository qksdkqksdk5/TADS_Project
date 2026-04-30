/* eslint-disable */
// src/modules/monitoring/components/MonitoringMap.jsx
import { useEffect, useRef, useState } from 'react';
import { loadKakaoMapSDK } from '../../traffic/loadKakaoMap';
import { fetchRoadGeo } from '../api';
import { loadRoadGeoCache, saveRoadGeoCache } from '../utils/roadGeoCache';

// ── 상수 ──────────────────────────────────────────────────────
const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };
const LEVEL_LABEL = { SMOOTH: '원활',    SLOW: '서행',    CONGESTED: '정체',    JAM: '정체'    };
const ROAD_LINE_GRAY = '#334155';

// 도로 키 → Overpass 검색 설정 (its_helper.py의 ROAD_CONFIG와 동기화)
// names     : OSM name 태그 목록
// bounds    : 도로 전체 범위 bbox (없으면 전체 검색)
// nameBounds: 이름별 개별 bbox — 링 도로 일부만 잘라낼 때 사용
const OVERPASS_ROAD_CONFIG = {
  gyeongbu:  { names: ['경부고속도로'],                    bounds: null, nameBounds: null },
  gyeongin: {
    // 경인고속도로(Route 1) + 제2경인고속도로(Route 110) 두 노선 모두 쿼리
    names: ['경인고속도로', '제2경인고속도로'],
    bounds: null,
    // 이름별 클리핑 — 서울외곽순환고속도로로 이어지는 동쪽 연결로(motorway_link)를 제거
    // 백엔드 its_helper.py 의 osm_name_bounds 와 동일한 값으로 유지해야 한다
    nameBounds: {
      '경인고속도로':    { minX: 126.55, maxX: 126.88, minY: 37.48, maxY: 37.56 },
      '제2경인고속도로': { minX: 126.55, maxX: 126.94, minY: 37.35, maxY: 37.47 },
    },
  },
  seohae:    { names: ['서해안고속도로'],                  bounds: null, nameBounds: null },
  jungang:   { names: ['중앙고속도로'],                    bounds: null, nameBounds: null },
  youngdong: {
    // 영동고속도로(Route 50): 인천기점→판교→여주→원주→강릉
    // 광주원주고속도로(Route 52) 구간은 its_helper.py/youngdong.json에서 패치로 추가됨
    // (브라우저 직접 Overpass 쿼리에 3개 이름 포함 시 65초 타임아웃 발생 → 1개로 유지)
    names:      ['영동고속도로'],
    bounds:     { minY: 37.1, minX: 126.5, maxY: 37.9, maxX: 129.0 },
    nameBounds: null,
  },
};

// Overpass 브라우저 직접 쿼리 엔드포인트 목록 (백엔드 its_helper.py와 동일하게 3개 유지)
// 서버 IP가 차단돼도 브라우저(사용자 IP)는 허용되는 경우가 많다.
// Overpass API는 Access-Control-Allow-Origin: * 로 CORS를 허용한다.
const OVERPASS_BROWSER_ENDPOINTS = [
  'https://overpass-api.de/api/interpreter',         // 1순위: 공식 서버 (독일)
  'https://overpass.kumi.systems/api/interpreter',   // 2순위: kumi.systems EU 미러
  'https://overpass.openstreetmap.fr/api/interpreter', // 3순위: OpenStreetMap 프랑스 미러
];

/**
 * 단일 Overpass 엔드포인트에 쿼리하고 GeoJSON을 반환하는 헬퍼.
 * 실패(타임아웃·HTTP 오류·빈 결과) 시 null을 반환한다.
 *
 * @param {string} endpoint - Overpass API URL
 * @param {string} query    - Overpass QL 쿼리 문자열
 * @param {number} timeoutMs - 타임아웃 밀리초 (기본 25초)
 * @returns {Promise<{type:'FeatureCollection', features:Array}|null>}
 */
async function fetchOneOverpass(endpoint, query, timeoutMs = 25000) {
  const ctrl = new AbortController();                // 타임아웃용 중단 컨트롤러
  const tid  = setTimeout(() => ctrl.abort(), timeoutMs); // 시간 초과 시 요청 취소
  try {
    const resp = await fetch(endpoint, {
      method:  'POST',
      // Overpass는 application/x-www-form-urlencoded POST를 표준으로 지원
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body:    `data=${encodeURIComponent(query)}`,
      signal:  ctrl.signal,                          // AbortController 신호 연결
    });
    clearTimeout(tid);                               // 응답 도착 → 타임아웃 타이머 해제

    if (!resp.ok) return null;                       // HTTP 4xx/5xx → 실패 처리

    const json     = await resp.json();
    const elements = json.elements || [];

    // way 타입이고 좌표가 2개 이상인 요소만 LineString으로 변환
    // name 태그를 properties에 포함 → fetchOverpassDirect 의 좌표 클리핑에서 사용
    const features = elements
      .filter(el => el.type === 'way' && (el.geometry?.length ?? 0) >= 2)
      .map(el => ({
        type: 'Feature',
        properties: {
          osm_id: el.id,
          name: el.tags?.name || '', // 도로 이름 (예: '수도권제1순환고속도로') — 클리핑 판별용
        },
        geometry: {
          type: 'LineString',
          coordinates: el.geometry.map(pt => [pt.lon, pt.lat]), // [경도, 위도] 순서
        },
      }));

    if (features.length === 0) return null;          // 유효한 도로 데이터 없음 → 실패 처리

    console.log(`[MonitoringMap] 브라우저 Overpass 성공 (${endpoint.split('/')[2]}): ${features.length}개 way`);
    return { type: 'FeatureCollection', features };  // 성공 → GeoJSON 반환
  } catch {
    clearTimeout(tid);                               // 오류 발생 시에도 타이머 해제
    return null;                                     // 타임아웃·네트워크 오류 → 실패 처리
  }
}

/**
 * 브라우저에서 직접 Overpass API에 쿼리해 도로 선형 GeoJSON을 가져온다.
 * 3개 엔드포인트를 동시에(병렬) 요청하고 가장 먼저 응답하는 결과를 사용한다.
 *
 * 기존 방식(순차): 엔드포인트1 실패(10초) → 엔드포인트2 시도 → 최대 20초 대기
 * 개선 방식(병렬): 3개 동시 시작 → 가장 빠른 쪽 결과 즉시 사용 → 실제 응답 시간만 대기
 *
 * bbox 지원: youngdong처럼 링 전체를 도는 도로를 포함할 때 해당 구간만 잘라낸다.
 *
 * @param {string} roadKey - 도로 키 (예: 'gyeongbu')
 * @returns {Promise<{type:'FeatureCollection', features:Array}|null>}
 *          성공 시 GeoJSON, 모든 엔드포인트 실패 시 null
 */
async function fetchOverpassDirect(roadKey) {
  const cfg = OVERPASS_ROAD_CONFIG[roadKey];          // 도로별 검색 설정
  if (!cfg) return null;                              // 지원하지 않는 도로 키이면 즉시 포기

  // 이름별 개별 bbox 전략 — 링 도로를 이름 단위로 잘라낸다
  // nameBounds에 해당 이름이 있으면 그 bbox 우선, 없으면 global bounds, 둘 다 없으면 bbox 없음
  const nameBounds = cfg.nameBounds || {};
  const nameLines = cfg.names
    .map(n => {
      const nb = nameBounds[n] || cfg.bounds;  // 이름별 bbox → global bounds 순으로 폴백
      const bboxStr = nb
        ? `(${nb.minY},${nb.minX},${nb.maxY},${nb.maxX})`  // Overpass way bbox 포맷
        : '';
      return `way["name"="${n}"]["highway"~"motorway|trunk|motorway_link"]${bboxStr};`;
    })
    .join('');

  // Overpass QL 쿼리 — 고속도로 선형 조회 (전역 bbox 없음, per-way bbox 사용)
  // timeout:60 = Overpass 서버 자체 처리 제한 (서해안 340km 등 장거리 도로 대응)
  const query =
    `[out:json][timeout:60];` +
    `(${nameLines});` +
    `out geom;`;

  // 모든 엔드포인트를 동시에 요청 → raceFirstValid로 첫 번째 유효 결과 선택
  // 한 서버가 빠르게 응답하면 나머지 느린 요청의 결과는 무시된다
  const result = await raceFirstValid(
    ...OVERPASS_BROWSER_ENDPOINTS.map(ep => fetchOneOverpass(ep, query, 45000)),
  );

  if (!result) {
    console.warn('[MonitoringMap] 브라우저 Overpass 전체 엔드포인트 실패');
    return null;
  }

  // ── All-or-nothing 클리핑 ───────────────────────────────────────────────
  // "좌표 일부만 남기기"를 하면 북부 링의 시작 구간(인천→부천 토막)이 남아
  // 지도에 잘못된 선이 그려진다.
  // bbox 밖 노드가 하나라도 있는 way 는 통째로 버린다.
  // 제2영동선 남쪽 호는 모든 노드가 bbox 안에 있으므로 정상적으로 포함된다.
  if (Object.keys(nameBounds).length > 0) {
    const clipped = result.features.filter(f => {
      const featureName = f.properties.name || '';     // 도로 이름 (예: '수도권제1순환고속도로')
      const clipB = nameBounds[featureName];            // 이 이름에 대한 클리핑 bbox
      if (!clipB) return true;                          // 클리핑 대상 아니면 그대로 통과

      // bbox 밖 노드가 하나라도 있으면 이 way 전체 제거 (북부 링 제거)
      return !f.geometry.coordinates.some(
        ([lon, lat]) =>
          lon < clipB.minX || lon > clipB.maxX ||
          lat < clipB.minY || lat > clipB.maxY,
      );
    });

    result.features = clipped;
    if (clipped.length === 0) return null;
  }

  return result;
}

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

// ── 병렬 fetch 헬퍼 ──────────────────────────────────────────
/**
 * 여러 Promise를 동시에 실행하고 null이 아닌 첫 번째 결과를 반환한다.
 * 모두 null이거나 오류면 null을 반환한다.
 * 기존의 순차 실행(백엔드 실패 → Overpass 시작) 대신 병렬로 실행해
 * 더 빠른 쪽의 결과를 즉시 사용한다.
 */
function raceFirstValid(...promises) {
  return new Promise(resolve => {
    let remaining = promises.length;                          // 아직 완료되지 않은 Promise 수
    promises.forEach(p =>
      Promise.resolve(p)
        .then(v  => { if (v != null) resolve(v); else if (--remaining === 0) resolve(null); })
        .catch(() => { if (--remaining === 0) resolve(null); }),
    );
  });
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

    // 피처 중점(중간 좌표)에서 가장 가까운 카메라로 이 way 전체 색상 결정
    // 이전: 각 좌표마다 레벨 계산 후 세그먼트 분할 → 좌표 2개짜리 짧은 way에서
    //        레벨 전환 경계가 생기면 1개짜리 토막이 버려져 선이 사라지는 버그 발생
    const midIdx = Math.floor(coords.length / 2);       // 중간 좌표 인덱스
    const [mLng, mLat] = coords[midIdx];                // 중간 좌표 [경도, 위도]
    let minD = Infinity, nearest = null;
    for (const cam of camList) {
      const d = dist2([mLng, mLat], [cam.lng, cam.lat]);
      if (d < minD) { minD = d; nearest = cam; }
    }
    // 3.3km(≈0.001 제곱도) 이내 카메라가 있으면 그 레벨로, 없으면 회색
    const level = minD < 0.001 ? nearest?.level : null;
    const color = LEVEL_COLOR[level] || ROAD_LINE_GRAY;
    colored.push({ coords, color, strokeWeight: level ? 6 : 4 });
  }

  return colored;
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
// serverRoadGeo: 부모(index.jsx)가 Socket.IO road_geo_ready 이벤트로 수신한 { geo, road }
// null이면 아직 서버로부터 데이터가 오지 않은 것 → 폴링 retry가 대신 처리
// road: SectionList에서 선택된 도로 키 ('gyeongbu' | 'jungang' | ...)
export default function MonitoringMap({ host, cameras, selectedId, onSelect, onViewItsCctv, itsCctvList = [], selectedItsId, serverRoadGeo, road = 'gyeongbu' }) {
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

  // ── 도로 선형 GeoJSON 로드 ────────────────────────────────
  // [주 경로] Socket.IO road_geo_ready 이벤트 수신 시 즉시 반영
  // serverRoadGeo = { geo, road } — 현재 선택된 road와 일치할 때만 반영한다
  // (경부선 보는 중에 다른 도로의 push가 와도 무시)
  useEffect(() => {
    if (
      serverRoadGeo?.road === road &&             // 현재 선택된 도로의 데이터인지 확인
      serverRoadGeo?.geo?.features?.length > 0    // 유효한 GeoJSON인지 확인
    ) {
      setRoadGeo(serverRoadGeo.geo);              // 서버 push 도착 → 즉시 도로선 반영
      saveRoadGeoCache(road, serverRoadGeo.geo);  // 다음 방문을 위해 캐시에도 저장
    }
  }, [serverRoadGeo, road]);

  // [보조 경로] 도로 변경 or 초기 로드 시 GeoJSON 가져오기
  //
  // 개선된 흐름:
  //   0. 도로 변경 즉시 → 기존 오버레이 초기화 + localStorage 캐시 즉시 표시
  //   1. 백엔드 fetchRoadGeo + 브라우저 Overpass 를 동시(병렬)로 실행
  //      → 먼저 유효한 응답이 오는 쪽을 사용 (raceFirstValid)
  //   2. 성공 시 localStorage에도 저장 (다음 방문 때 즉시 표시용)
  //   3. 둘 다 실패 → 최대 3회 재시도 (60초 간격)
  //
  // road가 바뀌면 effect가 재실행되므로 roadGeo 의존성 제외 (루프 방지 목적 유지)
  useEffect(() => {
    if (!host || !road) return;

    let cancelled = false;   // 언마운트 or 도로 재변경 시 진행 중 async 취소용
    let retries   = 0;       // 전체 사이클 재시도 횟수
    const MAX_RETRIES = 3;   // 최대 3회
    const RETRY_MS    = 60000; // 60초 — 백엔드 실패 캐시 TTL과 맞춤
    let timer = null;

    // ── 0단계: 도로가 바뀌면 기존 오버레이 즉시 초기화 ──────────────────
    setRoadGeo(null);

    // localStorage 캐시가 있으면 즉시 표시 (stale-while-revalidate 패턴)
    // 동시에 백그라운드에서 최신 데이터를 가져와 교체한다
    const cached = loadRoadGeoCache(road);
    if (cached) {
      setRoadGeo(cached); // 캐시 즉시 표시 → 사용자는 바로 오버레이를 본다
    }

    const load = async () => {
      if (cancelled) return;

      // ── 1단계: 백엔드 + Overpass 병렬 실행 ────────────────────────────
      // 기존: 백엔드 응답 대기 → 실패 시 Overpass 시작 (순차, 느림)
      // 개선: 두 요청을 동시에 시작, 먼저 유효한 데이터가 오는 쪽 사용 (빠름)
      const backendPromise = fetchRoadGeo(host, road)
        .then(res => res.data?.features?.length > 0 ? res.data : null)
        .catch(() => null); // 백엔드 오류는 무시

      const overpassPromise = fetchOverpassDirect(road); // 브라우저 직접 쿼리

      const geo = await raceFirstValid(backendPromise, overpassPromise);

      if (cancelled) return;

      if (geo) {
        setRoadGeo(geo);             // 지도에 도로선 반영
        saveRoadGeoCache(road, geo); // 다음 방문을 위해 캐시 저장
        return;                      // 완료
      }

      // ── 2단계: 둘 다 실패 → 재시도 예약 ───────────────────────────────
      // socket push(road_geo_ready)가 오면 위 useEffect가 먼저 처리하므로
      // 이 타이머는 socket push가 없을 경우의 마지막 보험이다
      if (retries < MAX_RETRIES) {
        retries++;
        timer = setTimeout(load, RETRY_MS);
      }
    };

    load();
    return () => {
      cancelled = true;              // 언마운트 or road 변경 시 진행 중 작업 취소
      if (timer) clearTimeout(timer);
    };
  }, [host, road]); // road 추가 — 도로 탭이 바뀌면 즉시 재실행

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
    // roadGeo가 null일 때도(도로 변경 직후) 기존 폴리라인을 반드시 지운다.
    // 이전: null이면 early return → 이전 도로 폴리라인이 화면에 남아있는 버그 발생
    polylinesRef.current.forEach(p => p.setMap(null));  // 기존 폴리라인 지도에서 제거
    polylinesRef.current = [];                           // ref 배열 초기화

    if (!mapRef.current || !roadGeo) return;             // 지도 미초기화 or 데이터 없음 → 그리기 건너뜀
    const map = mapRef.current;

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
        overlaysRef.current[camera_id].setMap(map);
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
        itsOverlayRef.current[camera_id].setMap(map);
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

      {/* 범례 — zIndex:100 으로 카카오맵 내부 레이어(타일·저작권 표시 등)보다 위에 고정 */}
      <div style={{
        position: 'absolute', bottom: '10px', right: '10px',
        background: 'rgba(15,23,42,0.85)', border: '1px solid #1e293b',
        borderRadius: '8px', padding: '6px 10px',
        fontSize: '10px', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '3px',
        pointerEvents: 'none', zIndex: 100,
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
