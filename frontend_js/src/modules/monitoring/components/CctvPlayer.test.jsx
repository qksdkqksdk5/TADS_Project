/* eslint-disable */
// src/modules/monitoring/components/CctvPlayer.test.jsx
// CctvPlayer 컴포넌트의 자동 재시도·실패 상태 UI를 검증하는 테스트

import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

// ── CctvPlayer 임포트 ──────────────────────────────────────────
// 내부 axios 호출을 mock으로 대체해 네트워크 없이 테스트한다
vi.mock('axios', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),  // tracks 폴링을 빈 배열로 응답
  },
}));

import CctvPlayer from './CctvPlayer';


// ─────────────────────────────────────────────────────────────────────────────
// 테스트 1: ItsProxyPlayer — 이미지 오류 시 자동 재시도
// ─────────────────────────────────────────────────────────────────────────────

describe('ItsProxyPlayer 자동 재시도', () => {
  beforeEach(() => {
    vi.useFakeTimers();   // setTimeout을 가짜 타이머로 대체해 즉시 제어한다
  });

  afterEach(() => {
    vi.useRealTimers();   // 테스트 후 실제 타이머 복원
  });

  it('이미지 오류 시 "재연결 중" 안내 문구가 표시된다', async () => {
    // itsCctv가 있으면 ItsProxyPlayer 모드로 렌더된다
    const cam = { camera_id: 'test_cam_1', name: '테스트 카메라', url: 'http://fake/stream' };

    const { container } = render(
      <CctvPlayer host="localhost" itsCctv={cam} />
    );

    // img 태그의 onError 이벤트를 수동으로 발생시킨다
    const img = container.querySelector('img');
    expect(img).not.toBeNull();

    await act(async () => {
      img.dispatchEvent(new Event('error'));   // 이미지 로드 실패 시뮬레이션
    });

    // 오류 후 "재연결 중" 문구가 화면에 나타나야 한다
    expect(screen.getByText(/재연결 중/)).toBeInTheDocument();
  });

  it('이미지 오류 후 5초(ITS_AUTO_RETRY_MS) 뒤 자동으로 재시도한다', async () => {
    const cam = { camera_id: 'test_cam_2', name: '테스트 카메라', url: 'http://fake/stream' };

    const { container } = render(
      <CctvPlayer host="localhost" itsCctv={cam} />
    );

    const img = container.querySelector('img');
    const srcBefore = img.src;   // 재시도 전 src (streamKey=0)

    // 오류 발생
    await act(async () => {
      img.dispatchEvent(new Event('error'));
    });

    // 5초 경과 시뮬레이션 (ITS_AUTO_RETRY_MS = 5000ms)
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    // streamKey가 증가하면 img의 key가 바뀌어 새 img 엘리먼트가 생성된다.
    // 재시도 후 "재연결 중" 문구가 사라져야 한다 (자동으로 imgError=false 설정)
    expect(screen.queryByText(/재연결 중/)).toBeNull();
  });
});


// ─────────────────────────────────────────────────────────────────────────────
// 테스트 2: MjpegPlayer — streamStatus에 따른 실패 UI 표시
// ─────────────────────────────────────────────────────────────────────────────

describe('MjpegPlayer 연결 실패 상태 UI', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('streamStatus 없으면 "연결 대기 중" 기본 안내를 표시한다', async () => {
    const { container } = render(
      <CctvPlayer host="localhost" cameraId="test_cam" />
    );

    // img 오류 발생 (streamStatus 없음)
    const img = container.querySelector('img');
    await act(async () => {
      img.dispatchEvent(new Event('error'));
    });

    expect(screen.getByText('연결 대기 중...')).toBeInTheDocument();
    // 연결 실패 오버레이는 표시되지 않아야 한다
    expect(screen.queryByText(/스트림 연결 실패/)).toBeNull();
  });

  it('streamStatus 있으면 실패 횟수와 재시도 안내를 표시한다', async () => {
    const streamStatus = { fail_count: 3, next_retry_in: 40 };

    const { container } = render(
      <CctvPlayer
        host="localhost"
        cameraId="test_cam"
        streamStatus={streamStatus}
      />
    );

    // img 오류 발생 (streamStatus 있음)
    const img = container.querySelector('img');
    await act(async () => {
      img.dispatchEvent(new Event('error'));
    });

    // 연결 실패 오버레이가 표시돼야 한다
    expect(screen.getByText(/스트림 연결 실패 \(3회\)/)).toBeInTheDocument();
    expect(screen.getByText(/40초 후 자동 재시도 예정/)).toBeInTheDocument();
    // "지금 다시 시도" 버튼이 표시돼야 한다
    expect(screen.getByRole('button', { name: /지금 다시 시도/ })).toBeInTheDocument();
  });

  it('"지금 다시 시도" 버튼 클릭 시 onRestartCamera가 호출된다', async () => {
    // userEvent는 실제 타이머가 필요하므로 fake timer를 사용하지 않는다
    vi.useRealTimers();

    const streamStatus = { fail_count: 2, next_retry_in: 20 };
    const mockRestart  = vi.fn(() => Promise.resolve());   // 재시작 콜백 mock

    const { container } = render(
      <CctvPlayer
        host="localhost"
        cameraId="my_camera"
        streamStatus={streamStatus}
        onRestartCamera={mockRestart}
      />
    );

    const img = container.querySelector('img');
    await act(async () => {
      img.dispatchEvent(new Event('error'));
    });

    const btn = screen.getByRole('button', { name: /지금 다시 시도/ });
    await userEvent.click(btn);

    // onRestartCamera가 cameraId('my_camera')를 인자로 호출됐는지 확인
    expect(mockRestart).toHaveBeenCalledWith('my_camera');
  });
});
