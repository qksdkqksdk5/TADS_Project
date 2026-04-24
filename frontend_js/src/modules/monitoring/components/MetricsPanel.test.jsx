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

// ═══════════════════════════════════════════════════════════════════════════════
// A. 방향별 뱃지 순서 — dir_label_a가 왼쪽, dir_label_b가 오른쪽
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 방향별 뱃지 순서', () => {

  it('dir_label_a=상행이면 "상행" 레이블이 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ dir_label_a: '상행', dir_label_b: '하행' })} />);

    // 5분 후 예측 섹션에도 방향 레이블이 표시되므로 getAllByText 사용
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
    // 이전 구조에서는 "정체 지수"라는 별도 섹션이 있었으나 통합 후 제거
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

    // 레벨 뱃지 + 예측 섹션 양쪽에서 "학습 중" 이 나타나므로 getAllByText 사용
    expect(screen.getAllByText('학습 중').length).toBeGreaterThan(0);
    // 예측 섹션에는 여전히 방향 레이블(상행/하행)이 표시되므로 존재 여부만 확인
    expect(screen.getAllByText('상행').length).toBeGreaterThan(0);
  });

  it('relearning=true 이면 "재보정 중" 단일 뱃지가 표시되어야 한다', () => {
    render(<MetricsPanel data={makeData({ relearning: true })} />);

    expect(screen.getByText('재보정 중')).toBeTruthy();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// D. 방향 기준 툴팁 (레벨 기준은 팝업 헤더로 이동됨)
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 방향 기준 툴팁', () => {

  it('기본 상태에서는 방향 기준 툴팁이 숨겨져 있어야 한다', () => {
    render(<MetricsPanel data={makeData()} />);

    // 툴팁 제목 "방향 기준 (CCTV 화면 기준)"은 hover 전에 보이면 안 됨
    expect(screen.queryByText(/CCTV 화면 기준/)).toBeNull();
  });

  it('레벨 기준 박스("레벨 기준")가 MetricsPanel에 없어야 한다 (팝업 헤더로 이동)', () => {
    // 레벨 기준은 CameraPopup 헤더로 이동했으므로 MetricsPanel에 없어야 한다
    render(<MetricsPanel data={makeData()} />);

    expect(screen.queryByText('레벨 기준')).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// E. 정체 예측 플레이스홀더
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 정체 예측 섹션', () => {

  it('"5분 후 예측" 섹션 레이블이 표시되어야 한다', () => {
    // PredictionBadge 구현 후 "정체 예측 준비 중" 플레이스홀더는 제거됨
    // 현재는 "5분 후 예측" 섹션 자체가 항상 표시된다
    render(<MetricsPanel data={makeData()} />);

    expect(screen.getByText('5분 후 예측')).toBeTruthy();
  });

  it('예측 데이터가 없으면 PredictionBadge에 "학습 중" 이 표시된다', () => {
    // prediction_a / prediction_b 를 전달하지 않으면 null → "학습 중" 표시
    render(<MetricsPanel data={makeData()} />);

    // 두 방향 모두 "학습 중" 이 나타나야 한다
    expect(screen.getAllByText('학습 중').length).toBeGreaterThanOrEqual(2);
  });
});
