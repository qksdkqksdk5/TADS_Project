// MetricsPanel.test.jsx
// 교통 모니터링 팀 — MetricsPanel 지표 표시 검증
// 실행: frontend_js/ 에서 `npx vitest run`

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MetricsPanel from './MetricsPanel';

// ── 공통 데이터 팩토리 ────────────────────────────────────────────────────────
// 학습 완료(is_learning=false) 상태의 최소 traffic_update 페이로드를 생성한다.
function makeData(overrides = {}) {
  return {
    level:             'SMOOTH',     // 두 방향 중 최악 레벨
    dir_label_a:       '상행',       // A방향 레이블 — 왼쪽 뱃지
    dir_label_b:       '하행',       // B방향 레이블 — 오른쪽 뱃지
    level_a:           'SMOOTH',     // A방향 레벨
    level_b:           'SMOOTH',     // B방향 레벨
    jam_a:             0.0,          // A방향 jam_score
    jam_b:             0.0,          // B방향 jam_score
    is_learning:       false,        // 학습 완료
    relearning:        false,        // 재보정 아님
    learning_progress: 0,
    learning_total:    0,
    ...overrides,
  };
}

// 1h/2h/3h 예측 데이터를 생성하는 헬퍼 (HistoricalPredictor.predict() 반환 형식)
function makePrediction(overrides = []) {
  const base = [
    { horizon_sec: 3600,  horizon_min: 60,  predicted_level: 'SMOOTH', confidence: 0.5, jam_score: 0.2, interpolated: false },
    { horizon_sec: 7200,  horizon_min: 120, predicted_level: 'SLOW',   confidence: 0.4, jam_score: 0.45, interpolated: false },
    { horizon_sec: 10800, horizon_min: 180, predicted_level: 'JAM',    confidence: 0.3, jam_score: 0.7, interpolated: true  },
  ];
  return overrides.length > 0 ? overrides : base;
}

// ═══════════════════════════════════════════════════════════════════════════════
// A. 방향별 뱃지 순서 — dir_label_a가 왼쪽, dir_label_b가 오른쪽
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 방향별 뱃지 순서', () => {

  it('dir_label_a=상행이면 "상행" 레이블이 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ dir_label_a: '상행', dir_label_b: '하행' })} />);

    // 예측 섹션에도 방향 레이블이 표시되므로 getAllByText 사용
    expect(screen.getAllByText('상행').length).toBeGreaterThan(0);
    expect(screen.getAllByText('하행').length).toBeGreaterThan(0);
  });

  it('dir_label_a=하행이면 "하행" 레이블이 먼저 표시되어야 한다 (카메라 기준 왼쪽)', () => {
    // 카메라 광학흐름 기준으로 A방향이 하행인 경우 — 하행이 왼쪽 뱃지
    render(<MetricsPanel data={makeData({ dir_label_a: '하행', dir_label_b: '상행' })} />);

    const labels = screen.getAllByText(/상행|하행/);
    // 첫 번째로 등장하는 레이블이 하행이어야 한다
    expect(labels[0].textContent).toBe('하행');
    expect(labels[1].textContent).toBe('상행');
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// B. 레벨 + 지수 통합 뱃지 표시
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 레벨·지수 통합 뱃지', () => {

  it('level_a=SLOW 이면 A방향 뱃지에 "서행"이 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ level_a: 'SLOW', level_b: 'SMOOTH' })} />);

    expect(screen.getByText('서행')).toBeTruthy();
    expect(screen.getByText('원활')).toBeTruthy();
  });

  it('level_a=JAM 이면 A방향 뱃지에 "정체"가 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ level_a: 'JAM', level_b: 'SLOW' })} />);

    expect(screen.getByText('정체')).toBeTruthy();
    expect(screen.getByText('서행')).toBeTruthy();
  });

  it('jam_a=0.73, jam_b=0.12 이면 두 수치가 소수점 2자리로 표시되어야 한다', () => {
    // 정체 레벨과 지수가 하나의 뱃지에 합쳐지므로 수치도 같이 표시되어야 한다
    render(<MetricsPanel data={makeData({ jam_a: 0.73, jam_b: 0.12 })} />);

    expect(screen.getByText('0.73')).toBeTruthy();
    expect(screen.getByText('0.12')).toBeTruthy();
  });

  it('별도 "정체 지수" 섹션 레이블이 없어야 한다 (통합 뱃지로 대체)', () => {
    render(<MetricsPanel data={makeData()} />);

    expect(screen.queryByText('정체 지수')).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// C. 학습 중 상태
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 학습 중 상태', () => {

  it('is_learning=true 이면 레벨 뱃지 영역에 "학습 중" 이 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ is_learning: true })} />);

    expect(screen.getAllByText('학습 중').length).toBeGreaterThan(0);
    expect(screen.getAllByText('상행').length).toBeGreaterThan(0);
  });

  it('relearning=true 이면 "재보정 중" 단일 뱃지가 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ relearning: true })} />);

    expect(screen.getByText('재보정 중')).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// D. 방향 기준 툴팁
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 방향 기준 툴팁', () => {

  it('기본 상태에서는 방향 기준 툴팁이 숨겨져 있어야 한다', () => {
    render(<MetricsPanel data={makeData()} />);

    expect(screen.queryByText(/CCTV 화면 기준/)).toBeNull();
  });

  it('레벨 기준 박스("레벨 기준")가 MetricsPanel에 없어야 한다 (팝업 헤더로 이동)', () => {
    render(<MetricsPanel data={makeData()} />);

    expect(screen.queryByText('레벨 기준')).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// E. 정체 예측 섹션 — 132차 3열(1h·2h·3h) UI
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 정체 예측 섹션 (132차 3열 UI)', () => {

  it('"정체 예측 (1h·2h·3h)" 섹션 레이블이 표시되어야 한다', () => {
    // 132차: "5분 후 예측" → "정체 예측 (1h·2h·3h)"
    render(<MetricsPanel data={makeData()} />);

    expect(screen.getByText('정체 예측 (1h·2h·3h)')).toBeTruthy();
  });

  it('"5분 후 예측" 레이블이 없어야 한다 (132차에서 제거됨)', () => {
    render(<MetricsPanel data={makeData()} />);

    expect(screen.queryByText('5분 후 예측')).toBeNull();
  });

  it('예측 데이터가 없으면 PredictionBadge에 "학습 중" 이 표시된다', () => {
    // prediction_a / prediction_b 를 전달하지 않으면 null → "학습 중" 표시
    render(<MetricsPanel data={makeData()} />);

    // 두 방향 모두 "학습 중" 이 나타나야 한다
    expect(screen.getAllByText('학습 중').length).toBeGreaterThanOrEqual(2);
  });

  it('예측 데이터가 있으면 시간대 헤더 "1h", "2h", "3h" 가 표시되어야 한다', () => {
    // 1h/2h/3h 3개 예측 데이터 제공
    render(<MetricsPanel data={makeData({
      prediction_a: makePrediction(),  // 3개 horizon
      prediction_b: makePrediction(),
    })} />);

    // 각 시간대 컬럼 헤더가 최소 1회 이상 표시되어야 한다
    expect(screen.getAllByText('1h').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2h').length).toBeGreaterThan(0);
    expect(screen.getAllByText('3h').length).toBeGreaterThan(0);
  });

  it('예측 데이터가 있으면 레벨 텍스트가 표시되어야 한다 (SMOOTH/SLOW/JAM)', () => {
    render(<MetricsPanel data={makeData({
      prediction_a: makePrediction(),
      prediction_b: makePrediction(),
    })} />);

    // SMOOTH(원활), SLOW(서행), JAM(정체) 레벨이 각각 표시되어야 한다
    expect(screen.getAllByText('원활').length).toBeGreaterThan(0);
    expect(screen.getAllByText('서행').length).toBeGreaterThan(0);
    expect(screen.getAllByText('정체').length).toBeGreaterThan(0);
  });

  it('특정 horizon 데이터가 없으면 해당 열에 "-" 가 표시되어야 한다', () => {
    // 1h만 있고 2h/3h 없는 경우 → 2h/3h 열에 "-" 표시
    render(<MetricsPanel data={makeData({
      prediction_a: [
        { horizon_sec: 3600, horizon_min: 60, predicted_level: 'SMOOTH', confidence: 0.5, jam_score: 0.2, interpolated: false },
      ],
      prediction_b: null,  // B방향은 학습 중
    })} />);

    // 데이터 없는 열은 "-" 로 표시된다
    expect(screen.getAllByText('-').length).toBeGreaterThan(0);
  });

  it('신뢰도(%) 텍스트가 표시되지 않아야 한다 (132차에서 제거됨)', () => {
    render(<MetricsPanel data={makeData({
      prediction_a: makePrediction(),
      prediction_b: makePrediction(),
    })} />);

    // "50%", "40%" 등 신뢰도 백분율 텍스트가 없어야 한다
    expect(screen.queryByText(/\d+%/)).toBeNull();
  });
});
