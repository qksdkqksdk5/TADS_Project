/* eslint-disable */
// src/modules/monitoring/hooks/useMonitoringSocket.js

// React 기본 훅 import
// useState  : 화면에 표시할 데이터를 저장하는 상자 (바뀌면 화면 자동 갱신)
// useEffect : 컴포넌트가 화면에 나타나거나 특정 값이 바뀔 때 실행할 코드 등록
// useRef    : 화면 갱신 없이 값을 저장하거나 DOM 요소를 직접 참조할 때 사용
// useCallback: 함수를 매 렌더링마다 새로 만들지 않고 재사용 — 불필요한 자식 리렌더 방지
import { useState, useEffect, useRef, useCallback } from 'react';

// socket.io-client: 서버와 실시간 양방향 통신(WebSocket)을 쉽게 쓸 수 있게 해주는 라이브러리
// io() 함수로 서버에 연결하면 이벤트를 주고받을 수 있다 (문자처럼 즉시 전달)
import { io } from 'socket.io-client';

/**
 * 모니터링 전용 Socket.IO 실시간 연결 훅.
 *
 * 역할:
 *   서버(Flask-SocketIO)와 WebSocket으로 상시 연결을 유지하면서
 *   카메라 상태 업데이트·정체 알림·역주행 알림 등을 실시간으로 수신한다.
 *   App.jsx의 공유 소켓과 분리된 독립 연결을 사용하므로,
 *   모니터링 탭이 닫혀도 다른 탭 소켓에 영향을 주지 않는다.
 *
 * @param {string} host      - 서버 호스트 (예: 'localhost', '192.168.0.10')
 * @param {object} callbacks - 이벤트 발생 시 호출할 콜백 함수 모음
 *                             { onAnomalyAlert, onWrongwayAlert, onResolved }
 * @returns {object} 화면 컴포넌트에서 사용할 상태값·함수 모음
 */
export function useMonitoringSocket(host, callbacks = {}) {

  // ── 상태(State) 선언 ───────────────────────────────────────────────────────
  // cameras: 현재 모니터링 중인 카메라들의 최신 상태를 담는 객체
  //   키: camera_id (문자열), 값: 서버가 보낸 traffic_update 데이터
  //   예: { 'ITS_001': { level: 'JAM', jam_a: 0.85, ... } }
  const [cameras, setCameras] = useState({});

  // eventLogs: 발생한 정체·역주행 이벤트 목록 (최대 100개 유지)
  //   각 항목에 is_resolved(처리 여부), received_at(수신 시각) 포함
  const [eventLogs, setEventLogs] = useState([]);

  // unresolvedCounts: 아직 처리되지 않은 이벤트 수
  //   화면 상단 알림 뱃지(빨간 숫자)에 표시된다
  const [unresolvedCounts, setUnresolvedCounts] = useState({
    congested: 0, // 정체(JAM/CONGESTED) 미처리 건수
    slow: 0,      // 서행(SLOW) 미처리 건수
    wrongway: 0,  // 역주행 미처리 건수
  });

  // connected: 서버와 소켓이 현재 연결되어 있는지 여부 (true/false)
  //   연결 끊김 시 화면에 "연결 끊김" 표시를 위해 사용한다
  const [connected, setConnected] = useState(false);

  // serverRoadGeo: 서버가 Overpass API에서 받아온 도로 선형 GeoJSON 데이터
  //   null → 아직 서버로부터 받지 못한 상태
  //   객체 → 수신 완료, MonitoringMap이 이 값을 감지해 지도에 도로선을 그린다
  const [serverRoadGeo, setServerRoadGeo] = useState(null);

  // streamFailures: 스트림(영상) 연결에 실패한 카메라들의 실패 정보
  //   키: camera_id, 값: { fail_count, next_retry_in, next_retry_at, failed_at }
  //   카메라가 복구(camera_stream_recovered)되면 해당 항목이 제거된다
  const [streamFailures, setStreamFailures] = useState({});

  // ── Ref 선언 ───────────────────────────────────────────────────────────────
  // socketRef: Socket.IO 연결 객체를 저장 — useEffect 바깥에서도 소켓에 접근하기 위해 ref 사용
  //   (state에 저장하면 변경 시 불필요한 리렌더가 발생하므로 ref 사용)
  const socketRef = useRef(null);

  // stoppedRef: 사용자가 "중지" 버튼을 누른 카메라 ID 집합(Set)
  //   중지 직후에도 서버가 traffic_update를 계속 보내오므로,
  //   이 집합에 있는 카메라 ID의 업데이트는 무시해 화면에 재추가되는 것을 막는다
  const stoppedRef = useRef(new Set());

  // callbackRef: 부모 컴포넌트가 전달한 콜백 함수들을 ref에 저장
  //   이유: 소켓 이벤트 핸들러는 useEffect 안에 등록되어 최초 콜백만 참조하는데,
  //   ref를 쓰면 소켓을 재생성하지 않고도 항상 최신 콜백을 호출할 수 있다
  const callbackRef = useRef(callbacks);

  // callbacks가 바뀔 때마다 ref를 최신 값으로 갱신한다
  // (의존성 배열 없음 → 매 렌더링마다 실행되어 ref를 항상 최신 상태로 유지)
  useEffect(() => { callbackRef.current = callbacks; });

  // ── 이벤트 해소 함수 ───────────────────────────────────────────────────────
  /**
   * 특정 이벤트를 "처리 완료" 상태로 변경한다.
   *
   * 역할: EventLog에서 "조치 완료" 또는 "조치 불필요" 버튼을 누르면 호출된다.
   *       해당 이벤트의 is_resolved를 true로 바꿔 줄긋기·투명도 처리를 유발한다.
   *
   * @param {string|number} eventId - 해소할 이벤트의 고유 ID
   * @param {string} reason - 'action'(조치 완료) | 'no_action'(조치 불필요)
   */
  const resolveEvent = useCallback((eventId, reason = 'action') => {
    setEventLogs(prev =>
      // 전체 이벤트 목록을 순회하면서 ID가 일치하는 항목만 is_resolved: true로 교체
      // 나머지는 그대로 유지 (불변성 원칙 — 기존 배열을 직접 수정하지 않는다)
      prev.map(ev => ev.id === eventId
        ? { ...ev, is_resolved: true, resolve_reason: reason } // 해당 이벤트: 해소 처리
        : ev                                                    // 나머지 이벤트: 그대로 유지
      )
    );
  }, []); // 의존성 없음 — 함수 내용이 바뀔 이유가 없으므로 최초 1회만 생성

  // ── 카메라 선택 emit 함수 ──────────────────────────────────────────────────
  /**
   * 사용자가 특정 카메라를 선택했음을 서버에 알린다.
   *
   * 역할: SectionList에서 카메라 항목을 클릭하면 호출된다.
   *       서버는 이 이벤트를 받아 해당 카메라의 상세 데이터를 이 클라이언트에게만 전송한다.
   *
   * @param {string} camera_id - 선택한 카메라의 ID
   */
  const emitSelectCamera = useCallback((camera_id) => {
    // ?. (옵셔널 체이닝): 소켓이 아직 연결되지 않았으면 emit을 호출하지 않고 조용히 무시
    socketRef.current?.emit('select_camera', { camera_id });
  }, []); // 의존성 없음 — socketRef는 ref이므로 변경돼도 리렌더를 유발하지 않는다

  // ── 소켓 연결 및 이벤트 핸들러 등록 ──────────────────────────────────────
  // host가 바뀔 때마다 소켓을 새로 연결한다 (예: 개발→운영 서버 전환 시)
  useEffect(() => {
    // host가 없으면 연결 시도 자체를 건너뜀 (컴포넌트 초기화 직후 방어)
    if (!host) return;

    // Socket.IO 서버에 연결 — http://호스트:5000 으로 접속
    // polling → websocket 순서로 시도: polling은 일반 HTTP라 방화벽 통과가 쉽고,
    // 연결 성공 후 websocket으로 업그레이드해 실시간 양방향 통신으로 전환한다
    const sock = io(`http://${host}:5000`, {
      transports: ['polling', 'websocket'], // 연결 방식: polling 먼저 시도 후 websocket 업그레이드
      reconnectionAttempts: 5,              // 연결 실패 시 최대 5번까지 재시도
      timeout: 5000,                        // 5초 안에 연결 안 되면 실패로 처리
    });

    // 생성한 소켓 객체를 ref에 저장 — useEffect 바깥의 emitSelectCamera에서도 접근 가능하도록
    socketRef.current = sock;

    // ── connect 이벤트: 서버와 연결 성공 시 ──────────────────────────────
    sock.on('connect', () => {
      setConnected(true); // 연결 상태를 true로 변경 → 화면에 "연결됨" 표시

      // 서버에 "모니터링 탭에 입장했다"고 알린다
      // 서버는 이 소켓 ID(SID)를 _monitoring_sids 목록에 등록하고,
      // 이전에 일시정지된 감지기가 있으면 자동으로 재개시킨다
      sock.emit('monitoring_join');
    });

    // ── disconnect 이벤트: 서버 연결이 끊겼을 때 ─────────────────────────
    // 네트워크 불안정·서버 재시작 등으로 끊기면 connected를 false로 변경
    sock.on('disconnect', () => setConnected(false));

    // ── traffic_update 이벤트: 카메라 상태 정기 업데이트 ─────────────────
    // 백엔드가 약 30프레임(1초)마다 각 카메라의 최신 교통 상태를 전송한다
    // data: { camera_id, level, jam_a, jam_b, level_a, level_b, is_learning, ... }
    sock.on('traffic_update', (data) => {
      // 사용자가 중지 버튼을 누른 카메라면 업데이트 무시
      // (중지 직후 서버가 보내는 마지막 패킷이 카메라를 재추가하는 것을 방지)
      if (stoppedRef.current.has(data.camera_id)) return;

      setCameras(prev => {
        const prevCam   = prev[data.camera_id];                            // 이전 상태 (없으면 undefined)
        const isActive  = data.level === 'SLOW' || data.level === 'JAM';   // 현재 정체/서행 여부
        const wasActive = prevCam?.level === 'SLOW' || prevCam?.level === 'JAM'; // 이전 정체/서행 여부

        // levelSince: SLOW 또는 JAM 상태가 처음 시작된 시각(ms)
        // 정체 지속 시간을 화면에 표시하기 위해 사용한다
        // - SMOOTH → SLOW/JAM 전환: 지금 시각을 기록
        // - 이미 SLOW/JAM였으면: 기존에 기록된 시각을 그대로 유지 (덮어쓰면 지속 시간이 초기화됨)
        // - SMOOTH로 돌아오면: null로 초기화 (지속 시간 표시 중단)
        let levelSince;
        if (!isActive) {
          levelSince = null;               // 정체 아님 → 지속 시간 초기화
        } else if (!wasActive) {
          levelSince = Date.now();         // 방금 정체 진입 → 현재 시각 기록
        } else {
          levelSince = prevCam?.levelSince ?? Date.now(); // 이미 정체 중 → 기존 시각 유지
        }

        // 기존 cameras 객체를 복사하고 해당 카메라 데이터만 교체 (불변성 유지)
        return { ...prev, [data.camera_id]: { ...data, levelSince } };
      });
    });

    // ── anomaly_alert 이벤트: 정체 이상 감지 알림 ────────────────────────
    // 백엔드가 SLOW 또는 JAM 상태를 처음 감지했을 때 한 번 전송한다 (매 프레임 아님)
    // data: { camera_id, level, jam_score, detected_at, direction, ... }
    sock.on('anomaly_alert', (data) => {
      setEventLogs(prev => [
        {
          event_type:  'anomaly',   // 이벤트 종류: 정체 이상
          is_resolved: false,       // 초기 상태: 미처리
          ...data,                  // 서버 데이터 덮어쓰기 (camera_id, level, detected_at 등)
          // id를 spread 뒤에 두는 이유: ...data 안에 data.id가 있으면 덮어써지는데,
          // data.id는 서버에서 보낸 DB id라 중복될 수 있어 클라이언트 고유 id를 강제 사용
          id:          Date.now() + Math.random(),
          // received_at: 클라이언트가 이 이벤트를 받은 시각(ms)
          // 서버의 detected_at은 UTC 나이브 문자열이라 브라우저가 KST(+9h)로 오해석해
          // 경과 시간이 9시간 부풀려지는 버그가 있어 클라이언트 수신 시각을 별도로 기록한다
          received_at: Date.now(),
        },
        ...prev.slice(0, 99), // 최대 100개 유지 — 오래된 것부터 밀려남
      ]);

      // 미처리 카운트 증가 — 화면 알림 뱃지(숫자)에 반영된다
      setUnresolvedCounts(prev => ({
        ...prev,
        // JAM 또는 CONGESTED 레벨이면 정체 카운트 +1, 아니면 그대로
        congested: (data.level === 'CONGESTED' || data.level === 'JAM')
          ? prev.congested + 1
          : prev.congested,
        // SLOW 레벨이면 서행 카운트 +1, 아니면 그대로
        slow: data.level === 'SLOW' ? prev.slow + 1 : prev.slow,
      }));

      // 부모 컴포넌트가 전달한 onAnomalyAlert 콜백 호출 (예: 사운드 알림 재생)
      // ?. 옵셔널 체이닝: 콜백이 없으면 에러 없이 조용히 무시
      callbackRef.current?.onAnomalyAlert?.(data);
    });

    // ── wrongway_alert 이벤트: 역주행 차량 감지 알림 ─────────────────────
    // 백엔드가 역주행 차량을 확정했을 때 전송한다
    // data: { camera_id, track_id, label, detected_at, ... }
    sock.on('wrongway_alert', (data) => {
      setEventLogs(prev => [
        {
          event_type:  'wrongway',  // 이벤트 종류: 역주행
          is_resolved: false,       // 초기 상태: 미처리
          ...data,                  // 서버 데이터 (camera_id, track_id 등)
          id:          Date.now() + Math.random(), // 클라이언트 고유 ID (anomaly와 동일 이유)
          received_at: Date.now(),  // 클라이언트 수신 시각 (9시간 오차 버그 방지, anomaly와 동일 이유)
        },
        ...prev.slice(0, 99), // 최대 100개 유지
      ]);

      // 역주행 미처리 카운트 +1
      setUnresolvedCounts(prev => ({ ...prev, wrongway: prev.wrongway + 1 }));

      // 부모 컴포넌트의 onWrongwayAlert 콜백 호출 (예: 경고음 재생)
      callbackRef.current?.onWrongwayAlert?.(data);
    });

    // ── road_geo_ready 이벤트: 도로 선형 GeoJSON 수신 ───────────────────
    // 서버가 Overpass API에서 도로 경로 데이터를 받아오면 이 이벤트로 push한다
    // 클라이언트가 폴링(주기적 요청)하지 않아도 되어 불필요한 HTTP 요청을 줄인다
    // data: { geo: GeoJSON 객체, road: 도로 키 (예: 'gyeongbu') }
    sock.on('road_geo_ready', (data) => {
      // geo.features 배열이 비어있으면 의미 없는 데이터이므로 무시
      if (data?.geo?.features?.length > 0) {
        setServerRoadGeo({
          geo:  data.geo,                 // GeoJSON 데이터 (지도에 선을 그리는 데 사용)
          road: data.road || 'gyeongbu', // 어느 고속도로 데이터인지 (road 필드가 없는 구버전은 기본값 사용)
        });
      }
    });

    // ── camera_stream_failed 이벤트: 카메라 스트림 연결 실패 알림 ─────────
    // 백엔드 MonitoringDetector가 5회 재연결에 모두 실패하고 지수 백오프 대기에 진입할 때 전송
    // data: { camera_id, fail_count, next_retry_in, next_retry_at }
    sock.on('camera_stream_failed', (data) => {
      setStreamFailures(prev => ({
        ...prev,                    // 기존 실패 목록 유지
        [data.camera_id]: {         // 실패한 카메라 정보 추가/갱신
          fail_count:    data.fail_count,     // 지금까지 몇 번 실패했는지
          next_retry_in: data.next_retry_in,  // 다음 재시도까지 남은 초 (카운트다운 표시용)
          next_retry_at: data.next_retry_at,  // 다음 재시도 예정 시각 (ISO 문자열)
          failed_at:     Date.now(),          // 클라이언트가 이 알림을 받은 시각 (표시용)
        },
      }));
    });

    // ── camera_stream_recovered 이벤트: 카메라 스트림 복구 알림 ──────────
    // 백엔드가 재시도 중 정상 프레임을 받으면 전송 → 실패 상태 아이콘을 화면에서 제거한다
    // data: { camera_id }
    sock.on('camera_stream_recovered', (data) => {
      setStreamFailures(prev => {
        const next = { ...prev };     // 기존 실패 목록 복사 (불변성 유지)
        delete next[data.camera_id]; // 복구된 카메라의 실패 상태 제거
        return next;
      });
    });

    // ── resolved 이벤트: 다른 클라이언트(혹은 서버)가 이벤트를 해소했을 때 ─
    // 현재는 같은 클라이언트에서 resolveEvent()로만 처리하지만,
    // 추후 다중 사용자 환경에서 서버 동기화를 위해 수신 준비를 해둔다
    // data: { camera_id, level }
    sock.on('resolved', (data) => {
      setEventLogs(prev => {
        let resolved = false; // 이미 한 건 해소했으면 다음 건은 건드리지 않기 위한 플래그

        return prev.map(ev => {
          // 조건: 아직 미처리 + 같은 camera_id + 아직 한 건도 해소 안 했음
          // → 가장 최근(위쪽) 미처리 이벤트 1건만 해소 처리
          if (!resolved && !ev.is_resolved && ev.camera_id === data.camera_id) {
            resolved = true;                      // 플래그 세트 → 이후 항목은 건드리지 않음
            return { ...ev, is_resolved: true }; // 해당 이벤트 해소 처리
          }
          return ev; // 나머지 이벤트는 그대로 유지
        });
      });

      // 해소된 이벤트의 레벨에 맞게 미처리 카운트 감소
      // Math.max(0, ...)로 음수 방지 (혹시 카운트가 이미 0이어도 안전)
      setUnresolvedCounts(prev => ({
        ...prev,
        congested: Math.max(0, prev.congested - (
          (data.level === 'CONGESTED' || data.level === 'JAM') ? 1 : 0
        )),
        slow: Math.max(0, prev.slow - (data.level === 'SLOW' ? 1 : 0)),
      }));

      // 부모 컴포넌트의 onResolved 콜백 호출
      callbackRef.current?.onResolved?.(data);
    });

    // ── 클린업 함수: 컴포넌트가 언마운트되거나 host가 바뀔 때 실행 ──────
    // 소켓 연결을 끊지 않으면 메모리 누수와 중복 이벤트 수신이 발생한다
    return () => sock.close();

  }, [host]); // host가 바뀔 때만 소켓을 새로 연결한다

  // ── 카메라 제거 함수 ───────────────────────────────────────────────────────
  /**
   * 지정한 카메라들을 화면에서 즉시 제거하고, 10초간 재추가를 방지한다.
   *
   * 역할: SectionList에서 "구간 중지" 버튼을 누르면 호출된다.
   *       중지 후에도 서버는 잠시 traffic_update를 보내오는데,
   *       stoppedRef에 ID를 10초간 유지해 이 업데이트들을 모두 무시한다.
   *
   * @param {string[]} cameraIds - 제거할 카메라 ID 배열
   */
  const removeCameras = useCallback((cameraIds) => {
    // stoppedRef Set에 중지된 카메라 ID들을 등록 → traffic_update 수신 시 무시 처리
    cameraIds.forEach(id => stoppedRef.current.add(id));

    // cameras 상태에서 해당 카메라들을 즉시 삭제 → 화면에서 사라짐 (시각적 피드백)
    setCameras(prev => {
      const next = { ...prev };                   // 기존 cameras 복사 (불변성 유지)
      cameraIds.forEach(id => delete next[id]);   // 중지된 카메라 삭제
      return next;                                // 갱신된 cameras 반환
    });

    // 10초 후 stoppedRef에서 ID를 제거 — 이후 해당 카메라가 다시 시작되면 정상 수신
    // (10초: 서버가 중지된 카메라의 마지막 패킷을 모두 보내고 멈출 때까지 충분한 시간)
    setTimeout(() => {
      cameraIds.forEach(id => stoppedRef.current.delete(id)); // 차단 해제
    }, 10000);

  }, []); // 의존성 없음 — stoppedRef, setCameras 모두 안정적인 참조

  // ── 반환값: 컴포넌트에서 사용할 상태·함수 모음 ────────────────────────────
  return {
    cameras,           // 현재 모니터링 중인 카메라 상태 객체 { camera_id: {...} }
    eventLogs,         // 정체·역주행 이벤트 목록 (최대 100개)
    unresolvedCounts,  // 미처리 이벤트 수 { congested, slow, wrongway }
    connected,         // 소켓 연결 여부 (true/false)
    emitSelectCamera,  // 카메라 선택 이벤트를 서버로 전송하는 함수
    resolveEvent,      // 특정 이벤트를 처리 완료로 변경하는 함수
    removeCameras,     // 카메라를 화면에서 제거하고 재추가를 10초간 막는 함수
    serverRoadGeo,     // 서버에서 받은 도로 선형 GeoJSON (null=미수신)
    streamFailures,    // 스트림 연결 실패 중인 카메라 정보 { camera_id: { fail_count, ... } }
  };
}
