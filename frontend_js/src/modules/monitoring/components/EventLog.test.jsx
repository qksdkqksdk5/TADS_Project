// EventLog.test.jsx
// 교통 모니터링 팀 — EventLog 경과 시간 계산 검증
// 실행: frontend_js/ 에서 `npx vitest run`

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import EventLog from './EventLog';

// ── 공통 이벤트 팩토리 ───────────────────────────────────────────────────────
// received_at: 클라이언트가 이벤트를 수신한 시각 (ms)
// detected_at: 서버가 감지한 시각 (UTC 나이브 문자열, 실제로는 9시간 전일 수 있음)
function makeEvent(overrides = {}) {
  return {
    id: 1,
    event_type: 'anomaly',
    camera_id: 'cam_001',
    level: 'SLOW',
    jam_score: 0.75,
    is_resolved: false,
    // detected_at: 9시간 전 UTC 나이브 문자열 (타임존 버그 재현)
    detected_at: new Date(Date.now() - 9 * 60 * 60 * 1000).toISOString().replace('T', ' ').split('.')[0],
    // received_at: 클라이언트 수신 시각 — 이 값 기준으로 경과 시간을 계산해야 한다
    received_at: Date.now(),
    ...overrides,
  };
}

// ── 테스트 ────────────────────────────────────────────────────────────────────
describe('EventLog', () => {
  // fake timer 로 시간 흐름을 제어한다
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ── 1. 경과 시간이 received_at 기준 0초에서 시작해야 한다 ─────────────────
  it('새 이벤트는 경과 시간이 0초에서 시작한다', () => {
    // received_at = 지금, detected_at = 9시간 전 → 0초여야 함
    const event = makeEvent({ received_at: Date.now() });

    render(
      <EventLog
        eventLogs={[event]}
        onSelectCamera={() => {}}
        onDismissWrongway={() => {}}
      />
    );

    // "0초" 가 화면에 있어야 한다
    expect(screen.getByText('0초')).toBeTruthy();
  });

  // ── 2. 시간이 지나면 경과 시간이 증가해야 한다 ───────────────────────────
  it('1초 후 경과 시간이 1초로 증가한다', () => {
    const now = Date.now();
    const event = makeEvent({ received_at: now });

    render(
      <EventLog
        eventLogs={[event]}
        onSelectCamera={() => {}}
        onDismissWrongway={() => {}}
      />
    );

    // 1초 경과 시뮬레이션
    act(() => { vi.advanceTimersByTime(1000); });

    expect(screen.getByText('1초')).toBeTruthy();
  });

  // ── 3. detected_at 이 9시간 전이어도 received_at 이 지금이면 0초 ──────────
  it('detected_at 타임존 버그가 있어도 received_at 기준이면 0초다', () => {
    // detected_at 을 9시간 전 UTC 나이브 문자열로 설정 (타임존 버그 재현)
    const nineHoursAgoStr = new Date(Date.now() - 9 * 60 * 60 * 1000)
      .toISOString()
      .replace('T', ' ')
      .split('.')[0]; // "YYYY-MM-DD HH:MM:SS" 형식

    const event = makeEvent({
      detected_at: nineHoursAgoStr,
      received_at: Date.now(), // 클라이언트 수신은 지금
    });

    render(
      <EventLog
        eventLogs={[event]}
        onSelectCamera={() => {}}
        onDismissWrongway={() => {}}
      />
    );

    // detected_at 기준이었다면 ~32400초 이상 나왔을 것 — 0초여야 한다
    expect(screen.getByText('0초')).toBeTruthy();
  });

  // ── 4. 해소된 이벤트는 경과 시간을 표시하지 않는다 ──────────────────────
  it('해소된 이벤트는 경과 시간 대신 "해소됨" 을 표시한다', () => {
    const event = makeEvent({ is_resolved: true, received_at: Date.now() });

    render(
      <EventLog
        eventLogs={[event]}
        onSelectCamera={() => {}}
        onDismissWrongway={() => {}}
      />
    );

    expect(screen.getByText('해소됨')).toBeTruthy();
    // 경과 시간(초)은 표시되지 않아야 한다
    expect(screen.queryByText('0초')).toBeNull();
  });
});

// ── useMonitoringSocket received_at 필드 검증 ─────────────────────────────
// 소켓 훅이 anomaly_alert / wrongway_alert 수신 시 received_at 을 추가하는지 확인
import { renderHook } from '@testing-library/react';
import { useMonitoringSocket } from '../hooks/useMonitoringSocket';

// socket.io-client 모킹
let mockHandlers = {};
const mockSocket = {
  on:    vi.fn((event, handler) => { mockHandlers[event] = handler; }),
  emit:  vi.fn(),
  close: vi.fn(),
};
vi.mock('socket.io-client', () => ({ io: vi.fn(() => mockSocket) }));

describe('useMonitoringSocket — received_at 필드', () => {
  beforeEach(() => {
    mockHandlers = {};
    mockSocket.on.mockClear();
    mockSocket.emit.mockClear();
    mockSocket.close.mockClear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('anomaly_alert 수신 시 이벤트에 received_at 필드가 추가된다', async () => {
    const { result, unmount } = renderHook(() =>
      useMonitoringSocket('localhost', {})
    );

    const fakeNow = 1_700_000_000_000; // 고정된 가짜 현재 시각
    vi.setSystemTime(fakeNow);

    // anomaly_alert 이벤트 발동 시뮬레이션
    act(() => {
      mockHandlers['anomaly_alert']?.({
        camera_id: 'cam_001',
        level: 'SLOW',
        jam_score: 0.7,
        detected_at: '2024-01-01 00:00:00', // 오래된 UTC 나이브 문자열
      });
    });

    // eventLogs[0].received_at 이 fakeNow 여야 한다
    expect(result.current.eventLogs[0]?.received_at).toBe(fakeNow);

    unmount();
  });

  it('wrongway_alert 수신 시 이벤트에 received_at 필드가 추가된다', async () => {
    const { result, unmount } = renderHook(() =>
      useMonitoringSocket('localhost', {})
    );

    const fakeNow = 1_700_000_001_000;
    vi.setSystemTime(fakeNow);

    act(() => {
      mockHandlers['wrongway_alert']?.({
        camera_id: 'cam_002',
        track_id: 42,
        detected_at: '2024-01-01 00:00:00',
      });
    });

    expect(result.current.eventLogs[0]?.received_at).toBe(fakeNow);

    unmount();
  });
});
