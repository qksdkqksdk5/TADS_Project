// useMonitoringSocket.test.js
// 교통 모니터링 팀 — monitoring_join emit 동작 검증
// 실행: frontend_js/ 에서 `npm test` 또는 `npx vitest run`

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useMonitoringSocket } from './useMonitoringSocket';

// ── socket.io-client 모킹 ──────────────────────────────────────────────────
// 실제 서버 없이 소켓 동작을 검증하기 위해 io() 를 가짜 구현으로 대체한다.

// 이벤트 핸들러 저장소 — on('connect', handler) 등을 기록한다.
let mockHandlers = {};

// emit 호출 기록 — 어떤 이벤트가 emit 됐는지 검증한다.
let mockEmitCalls = [];

// 가짜 소켓 객체
const mockSocket = {
  on: vi.fn((event, handler) => {
    // 이벤트 이름별 핸들러 저장
    mockHandlers[event] = handler;
  }),
  emit: vi.fn((event, ...args) => {
    // emit 호출 기록
    mockEmitCalls.push({ event, args });
  }),
  close: vi.fn(),
};

// socket.io-client 모듈 전체를 가짜로 대체
vi.mock('socket.io-client', () => ({
  io: vi.fn(() => mockSocket),
}));

// ── 테스트 ────────────────────────────────────────────────────────────────

describe('useMonitoringSocket', () => {
  beforeEach(() => {
    // 각 테스트 전 상태 초기화
    mockHandlers  = {};
    mockEmitCalls = [];
    mockSocket.on.mockClear();
    mockSocket.emit.mockClear();
    mockSocket.close.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('소켓 연결 시 monitoring_join 을 emit 한다', () => {
    // 훅 렌더링 — 내부에서 io() 가 호출되고 on('connect', ...) 등록됨
    const { unmount } = renderHook(() =>
      useMonitoringSocket('localhost', {})
    );

    // connect 핸들러가 등록됐는지 확인
    expect(mockHandlers['connect']).toBeDefined();

    // connect 이벤트 발동 시뮬레이션 (실제 서버 연결 대신 핸들러 직접 호출)
    mockHandlers['connect']();

    // monitoring_join 이 emit 됐는지 검증
    const joinEmit = mockEmitCalls.find(c => c.event === 'monitoring_join');
    expect(joinEmit).toBeDefined();

    unmount();
  });

  it('monitoring_join 은 connect 시에만 emit 된다 (disconnect 시에는 emit 안 함)', () => {
    const { unmount } = renderHook(() =>
      useMonitoringSocket('localhost', {})
    );

    // disconnect 이벤트 발동
    if (mockHandlers['disconnect']) {
      mockHandlers['disconnect']();
    }

    // disconnect 시에는 monitoring_join emit 이 없어야 함
    const joinEmits = mockEmitCalls.filter(c => c.event === 'monitoring_join');
    expect(joinEmits).toHaveLength(0);

    unmount();
  });

  it('언마운트 시 소켓을 close 한다', () => {
    const { unmount } = renderHook(() =>
      useMonitoringSocket('localhost', {})
    );

    unmount();

    // cleanup 함수에서 sock.close() 가 호출돼야 함
    expect(mockSocket.close).toHaveBeenCalledTimes(1);
  });
});
