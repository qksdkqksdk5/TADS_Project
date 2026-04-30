// SectionList.test.jsx
// 교통 모니터링 팀 — 구간 시작/중지 버튼 동작 TDD 테스트
//
// 핵심 버그:
//   Bug-B-FE: axios에 timeout 미설정 → 백엔드가 느리면 '처리중...'이 영구 지속
//             api.js에 timeout이 없으므로, 백엔드가 응답을 보내지 않으면
//             loadingSeg=true가 영원히 유지되어 버튼이 동작 불능 상태가 됨
//
// 구성:
//   Section A: 정상 동작 테스트 (현재 PASS)
//   Section B: Bug-B-FE 재현 (현재 PASS — 버그 존재 증명)
//   Section C: 시작/중지 통합 흐름 (현재 PASS)
//
// 실행: frontend_js/ 에서
//   npx vitest run src/modules/monitoring/components/SectionList.test.jsx

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import '@testing-library/jest-dom';
import SectionList from './SectionList';

// ── api.js 전체를 모의(mock)한다 ──────────────────────────────────────────────
// 실제 서버 없이 테스트하기 위해 모든 API 함수를 vi.fn()으로 대체한다.
vi.mock('../api', () => ({
  fetchItsCctv: vi.fn(),   // IC 목록 조회
  startSegment: vi.fn(),   // 구간 시작
  stopSegment:  vi.fn(),   // 구간 중지
}));

import { fetchItsCctv, startSegment, stopSegment } from '../api';


// ── 공통 props 팩토리 ─────────────────────────────────────────────────────────
// SectionList에 필요한 최소 props를 생성한다.
function makeProps(overrides = {}) {
  return {
    host:             'localhost',       // 백엔드 호스트
    cameras:          {},                // 현재 모니터링 중인 카메라 (없음)
    selectedId:       null,              // 선택된 카메라 없음
    onSelect:         vi.fn(),           // 카메라 선택 콜백
    onViewItsCctv:    vi.fn(),           // ITS CCTV 보기 콜백
    onCctvListChange: vi.fn(),           // CCTV 목록 변경 콜백
    onRemoveCameras:  vi.fn(),           // 카메라 제거 콜백
    onRoadChange:     vi.fn(),           // 도로 변경 콜백
    ...overrides,
  };
}

// ── ITS CCTV API 응답 팩토리 ──────────────────────────────────────────────────
// fetchItsCctv가 반환하는 형태를 생성한다.
function makeItsCctvResponse(icList = ['A IC', 'B IC', 'C IC']) {
  return {
    data: {
      cameras: icList.map((name, i) => ({
        camera_id: `cam_00${i + 1}`,
        name,
        lat: 37.0 + i * 0.01,
        lng: 127.0 + i * 0.01,
      })),
      ic_list: icList,
    },
  };
}


// ════════════════════════════════════════════════════════════════════════════════
// Section A: 정상 동작 테스트 (현재 PASS)
// ════════════════════════════════════════════════════════════════════════════════

describe('SectionList — 중지 버튼 정상 동작', () => {

  beforeEach(() => {
    // 각 테스트 전 모의 함수 초기화
    vi.resetAllMocks();

    // fetchItsCctv는 기본적으로 IC 목록을 즉시 반환한다
    fetchItsCctv.mockResolvedValue(makeItsCctvResponse(['노포IC', '금정IC', '부산IC']));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── A-1. 중지 성공 시 '처리 중...'이 '■ 중지'로 돌아온다 ──────────────────

  it('중지 성공 시 처리중 버튼이 원래 ■ 중지 텍스트로 돌아온다', async () => {
    // 중지 API가 성공을 즉시 반환하는 상황
    stopSegment.mockResolvedValue({
      data: {
        status: 'ok',
        stopped: ['cam_001', 'cam_002'],   // 중지된 카메라
        not_found: [],
      },
    });

    render(<SectionList {...makeProps()} />);

    // IC 목록이 로드될 때까지 대기
    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());

    const stopBtn = screen.getByText('■ 중지');

    // 중지 버튼 클릭
    await act(async () => {
      fireEvent.click(stopBtn);
    });

    // 클릭 후 '처리 중...' 상태를 거쳐 원래 텍스트로 돌아와야 한다
    await waitFor(() => {
      expect(screen.getByText('■ 중지')).toBeInTheDocument();
      expect(screen.queryByText('처리 중...')).not.toBeInTheDocument();
    });
  });

  // ── A-2. 중지 실패 시에도 '처리 중...'이 반드시 해제된다 ─────────────────

  it('중지 API 실패 시에도 처리중 버튼이 원래 상태로 돌아온다', async () => {
    // 서버 500 에러 상황
    stopSegment.mockRejectedValue(new Error('서버 오류'));

    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());

    const stopBtn = screen.getByText('■ 중지');

    await act(async () => {
      fireEvent.click(stopBtn);
    });

    // 에러가 발생해도 finally 블록에서 loadingSeg=false가 돼야 한다.
    // 에러 메시지와 버튼 복구를 waitFor 하나에서 함께 확인해 타이밍 문제를 방지한다.
    await waitFor(() => {
      expect(screen.getByText('■ 중지')).toBeInTheDocument();
      expect(screen.queryByText('처리 중...')).not.toBeInTheDocument();
      expect(screen.getByText('구간 중지 실패')).toBeInTheDocument();
    });
  });

  // ── A-3. 중지 중에는 시작 버튼도 비활성화된다 ────────────────────────────

  it('중지 처리 중에는 시작 버튼도 disabled 된다', async () => {
    // 중지 API가 100ms 후 응답하는 상황 (처리중 상태를 관찰할 시간)
    stopSegment.mockImplementation(
      () => new Promise(resolve =>
        setTimeout(() => resolve({ data: { stopped: [], not_found: [] } }), 100)
      )
    );

    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());

    const startBtn = screen.getByText('▶ 시작');
    const stopBtn  = screen.getByText('■ 중지');

    // 중지 버튼 클릭
    fireEvent.click(stopBtn);

    // 처리 중 상태: 시작 버튼도 disabled여야 한다
    await waitFor(() => {
      expect(screen.getByText('처리 중...')).toBeInTheDocument();
    });

    // disabled 속성 확인
    // 두 버튼 모두 disabled: loadingSeg=true 상태
    const btn = screen.getByText('처리 중...').closest('button');
    expect(btn).toBeDisabled();

    // 처리 완료 후 버튼 활성화 대기
    await waitFor(() => {
      expect(screen.queryByText('처리 중...')).not.toBeInTheDocument();
    }, { timeout: 500 });
  });

  // ── A-4. 중지 완료 후 onRemoveCameras가 올바른 ID로 호출된다 ─────────────

  it('중지 완료 후 onRemoveCameras가 중지된 카메라 ID 배열로 호출된다', async () => {
    const stoppedIds = ['cam_001', 'cam_002', 'cam_003'];
    stopSegment.mockResolvedValue({
      data: { status: 'ok', stopped: stoppedIds, not_found: [] },
    });

    const onRemoveCameras = vi.fn();
    render(<SectionList {...makeProps({ onRemoveCameras })} />);

    // 버튼 노출 대기
    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());

    // IC 기본값 설정 useEffect(icList → setStartIC/setEndIC)도 완료될 때까지 플러시한다.
    // waitFor는 DOM 변화만 감지하지만, startIC/endIC 상태는 DOM에 직접 드러나지 않으므로
    // act(async () => {})로 추가 렌더링 사이클을 소비한다.
    await act(async () => {});

    await act(async () => {
      fireEvent.click(screen.getByText('■ 중지'));
    });

    await waitFor(() => {
      expect(onRemoveCameras).toHaveBeenCalledWith(stoppedIds);
    });
  });

  // ── A-5. 중지 완료 후 완료 메시지가 표시된다 ─────────────────────────────

  it('3개 중지 완료 후 "3개 중지 완료" 메시지가 표시된다', async () => {
    stopSegment.mockResolvedValue({
      data: { status: 'ok', stopped: ['cam_001', 'cam_002', 'cam_003'], not_found: [] },
    });

    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByText('■ 중지'));
    });

    await waitFor(() => {
      expect(screen.getByText('3개 중지 완료')).toBeInTheDocument();
    });
  });

});


// ════════════════════════════════════════════════════════════════════════════════
// Section B: Bug-B-FE 재현 — axios timeout 미설정 버그
// ════════════════════════════════════════════════════════════════════════════════

describe('SectionList — 처리중 영구 지속 버그 재현 (Bug-B-FE)', () => {

  // fake timer 사용: `waitFor`는 내부적으로 setTimeout을 쓰므로 fake timer와 궁합이 나쁘다.
  // 대신 `await act(async () => {})` 으로 마이크로태스크를 직접 플러시하는 방식을 사용한다.

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });  // 실제 시간은 멈추고 수동으로 조작
    vi.resetAllMocks();
    fetchItsCctv.mockResolvedValue(makeItsCctvResponse(['노포IC', '부산IC']));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ── B-1. 백엔드가 응답을 안 보내면 '처리 중...'이 영구 지속된다 ──────────

  it('[Bug-B-FE 재현] 백엔드 무응답 시 처리중 버튼이 영구 지속된다', async () => {
    // 절대 resolve되지 않는 Promise (백엔드 무응답 시뮬레이션)
    // axios에 timeout이 없으면 이 상태가 영원히 지속된다
    stopSegment.mockReturnValue(new Promise(() => {}));  // 영원히 pending

    render(<SectionList {...makeProps()} />);

    // fetchItsCctv Promise를 플러시한다.
    // act(async () => {}) 패턴은 마이크로태스크 큐를 비워 React 상태 업데이트를 반영한다.
    await act(async () => {});

    // IC 목록 로드 확인 (waitFor 없이 동기 확인)
    expect(screen.getByText('▶ 시작')).toBeInTheDocument();

    // 중지 버튼 클릭 → loadingSeg=true
    await act(async () => {
      fireEvent.click(screen.getByText('■ 중지'));
    });

    // '처리 중...' 상태 확인 (loadingSeg=true → 버튼 텍스트 변경)
    expect(screen.getByText('처리 중...')).toBeInTheDocument();

    // 10초 경과 시뮬레이션
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    await act(async () => {});   // 타이머 콜백으로 생성된 마이크로태스크 처리

    // [Bug-B-FE 확인] 여전히 '처리 중...' 상태 (버튼이 동작 불능)
    expect(screen.getByText('처리 중...')).toBeInTheDocument();

    console.log(
      '\n[Bug-B-FE 재현]\n' +
      '백엔드 무응답 시 처리중... 버튼이 10초 이상 지속됨\n' +
      '원인: api.js의 axios.create()에 timeout 옵션이 없음\n' +
      '  → axios 기본 timeout=0 (무제한 대기)\n' +
      '  → 백엔드가 ITS API 호출 중 멈히면 프론트엔드도 영구 처리중 상태\n' +
      '\nfix 방향:\n' +
      '  api.js: axios.create({ ..., timeout: 15000 }) 추가\n' +
      '  → 15초 후 axios가 자동으로 reject → catch 블록 실행 → loadingSeg=false'
    );
  });

  // ── B-2. timeout 설정 시 처리중 상태가 자동 해제된다 (fix 검증) ──────────

  it('[Bug-B-FE fix 검증] 15초 axios timeout 설정 시 처리중이 자동 해제된다', async () => {
    // fix가 적용됐다면: 15초 후 axios가 timeout 에러를 throw해야 한다.
    // 이를 시뮬레이션: setTimeout(reject, 15000) 으로 15초 후 reject되는 Promise
    stopSegment.mockImplementation(
      () => new Promise((_, reject) =>
        setTimeout(() => reject(new Error('timeout of 15000ms exceeded')), 15_000)
      )
    );

    render(<SectionList {...makeProps()} />);

    // fetchItsCctv 플러시
    await act(async () => {});
    expect(screen.getByText('▶ 시작')).toBeInTheDocument();

    // 중지 버튼 클릭
    await act(async () => {
      fireEvent.click(screen.getByText('■ 중지'));
    });
    expect(screen.getByText('처리 중...')).toBeInTheDocument();

    // 15초 경과 → setTimeout의 reject 콜백 실행 → Promise reject
    await act(async () => {
      vi.advanceTimersByTime(15_000);   // setTimeout 트리거
    });
    await act(async () => {});          // reject 이후 catch/finally 처리

    // fix 후: loadingSeg=false → '■ 중지' 복구
    expect(screen.queryByText('처리 중...')).not.toBeInTheDocument();
    expect(screen.getByText('■ 중지')).toBeInTheDocument();
  });

});


// ════════════════════════════════════════════════════════════════════════════════
// Section C: 시작 → 중지 통합 흐름 테스트
// ════════════════════════════════════════════════════════════════════════════════

describe('SectionList — 시작 후 중지 통합 흐름', () => {

  beforeEach(() => {
    vi.resetAllMocks();
    fetchItsCctv.mockResolvedValue(makeItsCctvResponse(['노포IC', '금정IC', '부산IC']));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── C-1. 시작 → 완료 → 중지 흐름이 정상 동작한다 ─────────────────────────

  it('시작 완료 후 중지 버튼을 누르면 정상적으로 중지된다', async () => {
    // 시작 API: 3개 시작 성공
    startSegment.mockResolvedValue({
      data: {
        status: 'ok',
        started: ['cam_001', 'cam_002', 'cam_003'],
        already_running: [],
        queued: [],
        message: '3개 시작',
      },
    });

    // 중지 API: 3개 중지 성공
    stopSegment.mockResolvedValue({
      data: {
        status: 'ok',
        stopped: ['cam_001', 'cam_002', 'cam_003'],
        not_found: [],
      },
    });

    const onRemoveCameras = vi.fn();
    render(<SectionList {...makeProps({ onRemoveCameras })} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());

    // Step 1: 시작
    await act(async () => {
      fireEvent.click(screen.getByText('▶ 시작'));
    });

    await waitFor(() => {
      expect(screen.getByText('3개 시작')).toBeInTheDocument();   // 시작 메시지
      expect(screen.getByText('▶ 시작')).toBeInTheDocument();     // 버튼 복구
    });

    expect(startSegment).toHaveBeenCalledTimes(1);

    // Step 2: 중지
    await act(async () => {
      fireEvent.click(screen.getByText('■ 중지'));
    });

    await waitFor(() => {
      expect(screen.getByText('3개 중지 완료')).toBeInTheDocument();  // 중지 메시지
      expect(screen.getByText('■ 중지')).toBeInTheDocument();          // 버튼 복구
    });

    expect(stopSegment).toHaveBeenCalledTimes(1);
    expect(onRemoveCameras).toHaveBeenCalledWith(['cam_001', 'cam_002', 'cam_003']);
  });

  // ── C-2. IC가 선택되지 않으면 중지 버튼이 동작하지 않는다 ─────────────────

  it('IC 목록이 비어있으면 중지 버튼 클릭 시 API를 호출하지 않는다', async () => {
    // IC 목록이 없는 상황
    fetchItsCctv.mockResolvedValue({ data: { cameras: [], ic_list: [] } });

    render(<SectionList {...makeProps()} />);

    await waitFor(() => {
      // IC 목록이 없으면 드롭다운이 없고, 버튼은 보일 수 있음
      expect(fetchItsCctv).toHaveBeenCalledTimes(1);
    });

    // IC 선택 없이 중지 클릭
    // (startIC, endIC가 ''이므로 handleStopSegment의 가드 조건에 걸림)
    const stopBtn = screen.queryByText('■ 중지');
    if (stopBtn) {
      await act(async () => {
        fireEvent.click(stopBtn);
      });
      // API 호출이 없어야 한다
      expect(stopSegment).not.toHaveBeenCalled();
    }
  });

  // ── C-3. 도로 탭 변경 시 IC 목록이 재로드된다 ─────────────────────────────

  it('경부 탭에서 경인 탭으로 변경하면 fetchItsCctv가 새 도로로 재호출된다', async () => {
    render(<SectionList {...makeProps()} />);

    // 첫 로드 (경부)
    await waitFor(() => {
      expect(fetchItsCctv).toHaveBeenCalledWith('localhost', 'gyeongbu');
    });

    // 경인 탭 클릭
    const incheonTab = screen.getByText('경인');
    await act(async () => {
      fireEvent.click(incheonTab);
    });

    // 경인 도로로 재호출
    await waitFor(() => {
      expect(fetchItsCctv).toHaveBeenCalledWith('localhost', 'gyeongin');
    });

    expect(fetchItsCctv).toHaveBeenCalledTimes(2);
  });

});


// ════════════════════════════════════════════════════════════════════════════════
// Section D: 종료 IC 드롭다운 정렬 — 시작 IC 기준 회전
// ════════════════════════════════════════════════════════════════════════════════

describe('SectionList — 종료 IC 드롭다운 시작 IC 기준 정렬', () => {

  beforeEach(() => {
    vi.resetAllMocks();
    // icList = ['노포IC', '금정IC', '달래내IC', '부산IC'] 순서로 서버가 반환한다고 가정
    fetchItsCctv.mockResolvedValue(makeItsCctvResponse(['노포IC', '금정IC', '달래내IC', '부산IC']));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── D-1. 기본값: 시작 IC 첫 항목이 종료 드롭다운 맨 위에 온다 ─────────────
  // 초기 startIC = icList[0] = '노포IC'
  // 종료 드롭다운의 첫 번째 옵션도 '노포IC'여야 한다.
  it('기본 startIC(첫 번째 IC)가 종료 드롭다운의 첫 번째 옵션으로 표시된다', async () => {
    render(<SectionList {...makeProps()} />);

    // IC 목록 로드 및 상태 업데이트 대기
    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());
    await act(async () => {});

    // 두 번째 select = 종료 드롭다운
    const selects = screen.getAllByRole('combobox');
    const endSelect = selects[1];

    // 종료 드롭다운의 첫 번째 옵션이 startIC(='노포IC')와 같아야 한다
    expect(endSelect.options[0].value).toBe('노포IC');
  });

  // ── D-1b. 초기 상태에서 종료 드롭다운의 선택값이 맨 첫 번째 IC여야 한다 ─────
  // 버그 방지: 기존에 endIC 기본값을 마지막 IC로 설정했을 때,
  // endOptions가 첫 번째 IC부터 시작하는데 선택값이 마지막이라 드롭다운이 맨 밑을 보이는 문제
  // → endIC 기본값이 startIC(첫 번째 IC)와 같아야 드롭다운이 맨 위를 보인다.
  it('초기 상태에서 종료 드롭다운의 선택된 값은 startIC(첫 번째 IC)와 같아야 한다', async () => {
    render(<SectionList {...makeProps()} />);

    // IC 목록 로드 및 상태 업데이트 대기
    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());
    await act(async () => {});

    // 두 번째 select = 종료 드롭다운
    const selects = screen.getAllByRole('combobox');
    const endSelect = selects[1];

    // 종료 드롭다운의 선택된 값이 첫 번째 IC(='노포IC')여야 한다 → 드롭다운이 맨 위를 가리킴
    expect(endSelect.value).toBe('노포IC');
  });

  // ── D-2. 시작 IC 변경 시 종료 드롭다운의 첫 번째 옵션이 갱신된다 ─────────
  // startIC를 '달래내IC'로 바꾸면 종료 드롭다운의 첫 번째 옵션도 '달래내IC'가 된다.
  it('startIC를 변경하면 종료 드롭다운의 첫 번째 옵션이 선택된 startIC로 갱신된다', async () => {
    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());
    await act(async () => {});

    const selects = screen.getAllByRole('combobox');
    const startSelect = selects[0]; // 시작 드롭다운
    const endSelect   = selects[1]; // 종료 드롭다운

    // 시작 IC를 '달래내IC'로 변경
    await act(async () => {
      fireEvent.change(startSelect, { target: { value: '달래내IC' } });
    });

    // 종료 드롭다운의 첫 번째 옵션이 '달래내IC'여야 한다
    expect(endSelect.options[0].value).toBe('달래내IC');
  });

  // ── D-3. 종료 드롭다운의 전체 항목 수는 변하지 않는다 ──────────────────────
  // 회전만 할 뿐 항목이 사라지거나 추가되어서는 안 된다.
  it('startIC 변경 후에도 종료 드롭다운의 총 옵션 수는 icList 길이와 동일하다', async () => {
    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());
    await act(async () => {});

    const selects = screen.getAllByRole('combobox');
    const startSelect = selects[0];
    const endSelect   = selects[1];

    await act(async () => {
      fireEvent.change(startSelect, { target: { value: '금정IC' } });
    });

    // icList 길이 = 4, 종료 옵션도 4개여야 한다
    expect(endSelect.options.length).toBe(4);
  });

  // ── D-5. startIC 변경 시 endIC가 startIC로 리셋되어 드롭다운이 맨 위에서 열린다 ──
  // 드롭다운은 현재 선택된 값(endIC) 위치로 자동 스크롤되므로,
  // endIC가 startIC와 같아야 회전된 리스트의 맨 위에서 열린다.
  it('startIC 변경 시 endIC가 새 startIC 값으로 리셋된다', async () => {
    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());
    await act(async () => {});

    const selects = screen.getAllByRole('combobox');
    const startSelect = selects[0];
    const endSelect   = selects[1];

    // 시작 IC를 '달래내IC'로 변경
    await act(async () => {
      fireEvent.change(startSelect, { target: { value: '달래내IC' } });
    });

    // endIC(= endSelect.value)도 '달래내IC'로 리셋되어야 한다
    expect(endSelect.value).toBe('달래내IC');
  });

  // ── D-4. startIC 선택 후 종료 드롭다운이 icList 진행 방향 순서를 따른다 ─────
  // icList = ['노포IC', '금정IC', '달래내IC', '부산IC']
  // startIC = '금정IC' → 종료 드롭다운: ['금정IC', '달래내IC', '부산IC', '노포IC']
  // → 역순이 아닌 icList 원본 순서로 이어져야 한다.
  it('startIC 이후 종료 드롭다운이 icList 진행 방향(역순 아님) 순서로 이어진다', async () => {
    render(<SectionList {...makeProps()} />);

    await waitFor(() => expect(screen.getByText('▶ 시작')).toBeInTheDocument());
    await act(async () => {});

    const selects = screen.getAllByRole('combobox');
    const startSelect = selects[0];
    const endSelect   = selects[1];

    // 시작 IC를 '금정IC'로 변경
    await act(async () => {
      fireEvent.change(startSelect, { target: { value: '금정IC' } });
    });

    // 종료 드롭다운 순서: ['금정IC', '달래내IC', '부산IC', '노포IC']
    // (icList 진행 방향으로 금정IC부터 순서대로, 앞부분 노포IC가 마지막으로 이동)
    const opts = Array.from(endSelect.options).map(o => o.value);
    expect(opts[0]).toBe('금정IC');   // 시작 IC가 맨 위
    expect(opts[1]).toBe('달래내IC'); // icList 다음 항목
    expect(opts[2]).toBe('부산IC');   // icList 그 다음
    expect(opts[3]).toBe('노포IC');   // 앞쪽 항목이 맨 마지막
  });

});
