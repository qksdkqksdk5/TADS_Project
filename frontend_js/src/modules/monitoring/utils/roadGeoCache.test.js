// roadGeoCache.test.js
// localStorage 기반 도로 GeoJSON 캐시 유틸 단위 테스트
// TDD Red 단계: 구현 전 먼저 작성 → 현재 실패해야 정상

import { describe, it, expect, beforeEach } from 'vitest';
import { loadRoadGeoCache, saveRoadGeoCache } from './roadGeoCache';

// ── localStorage 모킹 ─────────────────────────────────────────
// jsdom 환경에도 localStorage가 있지만, 테스트 간 격리를 보장하기 위해 직접 구현
const localStorageMock = (() => {
  let store = {};  // 실제 저장소 역할을 하는 객체
  return {
    getItem:    (key)        => store[key] ?? null,            // 없으면 null 반환
    setItem:    (key, value) => { store[key] = value; },       // 값 저장
    removeItem: (key)        => { delete store[key]; },        // 항목 삭제
    clear:      ()           => { store = {}; },               // 전체 초기화
  };
})();

// globalThis.localStorage 를 모킹으로 교체
Object.defineProperty(globalThis, 'localStorage', {
  value:      localStorageMock,
  writable:   true,
  configurable: true,
});

// ── 테스트용 GeoJSON 샘플 ──────────────────────────────────────
const SAMPLE_GEO = {
  type: 'FeatureCollection',
  features: [{
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[127.0, 37.5], [127.1, 37.4]] },
    properties: { osm_id: 1 },
  }],
};

// ── loadRoadGeoCache 테스트 ───────────────────────────────────
describe('loadRoadGeoCache', () => {

  // 각 테스트 전 저장소 초기화 (테스트 간 상태 오염 방지)
  beforeEach(() => localStorageMock.clear());

  it('캐시가 없으면 null을 반환한다', () => {
    // 아직 저장한 적 없으므로 null 이어야 한다
    expect(loadRoadGeoCache('gyeongbu')).toBeNull();
  });

  it('saveRoadGeoCache로 저장한 GeoJSON을 그대로 반환한다', () => {
    // 저장 후 불러오면 동일한 객체가 나와야 한다
    saveRoadGeoCache('gyeongbu', SAMPLE_GEO);
    const result = loadRoadGeoCache('gyeongbu');
    expect(result).toEqual(SAMPLE_GEO);
  });

  it('저장한 지 25시간이 지난 캐시는 만료로 처리해 null을 반환한다', () => {
    // 25시간 전 타임스탬프로 직접 저장 (만료 경계 테스트)
    const expiredTs = Date.now() - 25 * 60 * 60 * 1000;
    localStorageMock.setItem(
      'road_geo_v1_gyeongbu',
      JSON.stringify({ geo: SAMPLE_GEO, ts: expiredTs }),
    );
    expect(loadRoadGeoCache('gyeongbu')).toBeNull();
  });

  it('저장한 지 23시간인 캐시는 유효하므로 반환한다', () => {
    // 23시간 전 → 아직 만료 아님
    const recentTs = Date.now() - 23 * 60 * 60 * 1000;
    localStorageMock.setItem(
      'road_geo_v1_gyeongbu',
      JSON.stringify({ geo: SAMPLE_GEO, ts: recentTs }),
    );
    expect(loadRoadGeoCache('gyeongbu')).toEqual(SAMPLE_GEO);
  });

  it('다른 도로 키(jungang)에 저장해도 gyeongbu에는 영향 없다', () => {
    // 도로 키별로 독립적으로 저장되어야 한다
    saveRoadGeoCache('jungang', SAMPLE_GEO);
    expect(loadRoadGeoCache('gyeongbu')).toBeNull();
  });

  it('localStorage 값이 유효하지 않은 JSON 이면 null을 반환한다', () => {
    // 손상된 캐시가 있어도 예외 없이 null 처리
    localStorageMock.setItem('road_geo_v1_gyeongbu', 'not-valid-json!!!');
    expect(loadRoadGeoCache('gyeongbu')).toBeNull();
  });
});

// ── saveRoadGeoCache 테스트 ───────────────────────────────────
describe('saveRoadGeoCache', () => {

  beforeEach(() => localStorageMock.clear());

  it('저장 후 로드하면 원본과 동일한 GeoJSON을 반환한다', () => {
    saveRoadGeoCache('jungang', SAMPLE_GEO);
    expect(loadRoadGeoCache('jungang')).toEqual(SAMPLE_GEO);
  });

  it('같은 키로 덮어쓰면 최신 값을 반환한다', () => {
    // 첫 번째 저장
    saveRoadGeoCache('gyeongbu', SAMPLE_GEO);
    // 다른 데이터로 덮어쓰기
    const newGeo = { ...SAMPLE_GEO, features: [] };
    saveRoadGeoCache('gyeongbu', newGeo);
    expect(loadRoadGeoCache('gyeongbu')).toEqual(newGeo);
  });

  it('localStorage.setItem이 예외를 던져도 saveRoadGeoCache는 예외를 던지지 않는다', () => {
    // 스토리지 용량 초과(QuotaExceededError) 등 → 캐시 실패는 치명적이지 않아야 한다
    const original = localStorageMock.setItem;
    localStorageMock.setItem = () => { throw new Error('QuotaExceededError'); };
    expect(() => saveRoadGeoCache('gyeongbu', SAMPLE_GEO)).not.toThrow();
    localStorageMock.setItem = original;  // 복구
  });
});
