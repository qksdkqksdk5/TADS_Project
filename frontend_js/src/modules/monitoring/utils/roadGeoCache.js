// src/modules/monitoring/utils/roadGeoCache.js
// 도로 선형 GeoJSON의 localStorage 캐시 유틸리티.
// 반복 방문 시 Overpass 쿼리를 기다리지 않고 즉시 지도에 도로선을 표시하기 위해 사용한다.

// 스키마 변경 시 버전을 올리면 이전 캐시가 자동 무효화된다
// v6: youngdong.json에 광주원주고속도로(Route 52, 227개 way) 병합 → 캐시 무효화
const CACHE_VERSION = 'v6';

// 캐시 유효 시간 — 24시간 (하루에 한 번 갱신으로 충분)
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

// localStorage 키 생성 규칙: "road_geo_<버전>_<도로키>"
const cacheKey = (roadKey) => `road_geo_${CACHE_VERSION}_${roadKey}`;

/**
 * localStorage에서 도로 GeoJSON 캐시를 불러온다.
 * 캐시가 없거나 만료됐으면 null을 반환한다.
 *
 * @param {string} roadKey - 도로 키 (예: 'gyeongbu', 'jungang')
 * @returns {object|null} 유효한 GeoJSON FeatureCollection, 또는 null
 */
export function loadRoadGeoCache(roadKey) {
  try {
    const raw = localStorage.getItem(cacheKey(roadKey)); // 저장된 JSON 문자열 읽기
    if (!raw) return null;                                // 캐시 없음

    const { geo, ts } = JSON.parse(raw);                  // geo: GeoJSON, ts: 저장 시각(ms)

    // 저장한 지 TTL 이상 지났으면 만료로 처리
    if (Date.now() - ts > CACHE_TTL_MS) return null;

    return geo; // 유효한 캐시 반환
  } catch {
    // JSON 파싱 오류·localStorage 접근 오류 → 없는 것으로 처리 (치명적이지 않음)
    return null;
  }
}

/**
 * 도로 GeoJSON을 localStorage에 저장한다.
 * 저장에 실패해도 예외를 던지지 않는다 (용량 초과 등은 무시).
 *
 * @param {string} roadKey - 도로 키
 * @param {object} geo     - GeoJSON FeatureCollection
 */
export function saveRoadGeoCache(roadKey, geo) {
  try {
    localStorage.setItem(
      cacheKey(roadKey),
      JSON.stringify({ geo, ts: Date.now() }), // 저장 시각 함께 기록 (TTL 계산용)
    );
  } catch {
    // QuotaExceededError 등 → 무시 (캐시 실패는 기능에 영향 없음)
  }
}
