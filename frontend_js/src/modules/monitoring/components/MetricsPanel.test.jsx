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
    level:             'SMOOTH',     // 기본: 원활
    is_learning:       false,        // 학습 완료
    relearning:        false,        // 재보정 아님
    learning_progress: 0,
    learning_total:    0,
    jam_up:            0.0,          // 상행 정체지수
    jam_down:          0.0,          // 하행 정체지수
    vehicle_count:     0,            // 차량 수
    affected:          0,            // 정체 차량 수
    occupancy:         0.0,          // 점유율 (0~1)
    avg_speed:         1.0,          // 정규화 속도 (0~100 스케일, 100 = 기준 대비 100%)
    duration_sec:      0,            // 지속 시간
    ...overrides,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// A. avg_speed 표시 — 이중 곱셈 금지
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — avg_speed 표시', () => {

  it('[Red] avg_speed=4.0 이면 "4%" 로 표시해야 한다 (400%가 아님)', () => {
    // 백엔드 get_avg_speed()는 norm_speed_ratio * 100 을 반환한다.
    // avg_speed=4.0 은 이미 "4%" 를 뜻한다.
    // 프론트엔드가 * 100 을 또 하면 400% 가 됨 → 버그
    render(<MetricsPanel data={makeData({ avg_speed: 4.0 })} />);

    // "기준 대비 4%" 가 화면에 있어야 한다
    expect(screen.getByText(/기준 대비 4%/)).toBeTruthy();
    // "400%" 는 화면에 없어야 한다
    expect(screen.queryByText(/400%/)).toBeNull();
  });

  it('avg_speed=100.0 이면 "기준 대비 100%" 로 표시해야 한다', () => {
    // 기준 속도와 동일한 경우
    render(<MetricsPanel data={makeData({ avg_speed: 100.0 })} />);

    expect(screen.getByText(/기준 대비 100%/)).toBeTruthy();
    // 10000% 는 절대 나오면 안 됨
    expect(screen.queryByText(/10000%/)).toBeNull();
  });

  it('avg_speed=50.5 이면 반올림해서 "기준 대비 51%" 로 표시해야 한다', () => {
    // Math.round(50.5) = 51
    render(<MetricsPanel data={makeData({ avg_speed: 50.5 })} />);

    expect(screen.getByText(/기준 대비 51%/)).toBeTruthy();
  });

  it('avg_speed=0.0 이면 "기준 대비 0%" 로 표시해야 한다', () => {
    // 완전 정지 상태
    render(<MetricsPanel data={makeData({ avg_speed: 0.0 })} />);

    expect(screen.getByText(/기준 대비 0%/)).toBeTruthy();
  });

  it('학습 중(is_learning=true)이면 avg_speed 대신 "-" 를 표시해야 한다', () => {
    // 학습 중엔 속도 지표가 의미 없으므로 "-" 표시
    render(<MetricsPanel data={makeData({ is_learning: true })} />);

    // 학습 중이면 "-" 가 상대 속도 칸에 표시됨 (여러 개가 있을 수 있어 getAllByText 사용)
    const dashes = screen.getAllByText('-');
    expect(dashes.length).toBeGreaterThan(0);
    // 속도 수치는 표시되면 안 됨
    expect(screen.queryByText(/기준 대비/)).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// B. 차량 수 / 정체 차량 표시
// ═══════════════════════════════════════════════════════════════════════════════

describe('MetricsPanel — 차량 수 표시', () => {

  it('vehicle_count=34 이면 "34대" 로 표시해야 한다', () => {
    render(<MetricsPanel data={makeData({ vehicle_count: 34 })} />);

    expect(screen.getByText('34대')).toBeTruthy();
  });

  it('affected=2 이면 "2대" 로 표시해야 한다', () => {
    render(<MetricsPanel data={makeData({ affected: 2 })} />);

    expect(screen.getByText('2대')).toBeTruthy();
  });
});
