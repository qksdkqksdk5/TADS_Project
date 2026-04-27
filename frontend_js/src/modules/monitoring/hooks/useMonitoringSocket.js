/* eslint-disable */
// src/modules/monitoring/hooks/useMonitoringSocket.js
import { useState, useEffect, useRef, useCallback } from 'react';
import { io } from 'socket.io-client';

/**
 * 모니터링 전용 Socket.IO 훅.
 * App.jsx 공유 소켓과 분리된 독립 연결을 사용한다.
 *
 * @param {string} host  - 서버 호스트명
 * @param {object} callbacks - 이벤트 콜백 { onAnomalyAlert, onWrongwayAlert, onResolved }
 */
export function useMonitoringSocket(host, callbacks = {}) {
  const [cameras,          setCameras]          = useState({});
  const [eventLogs,        setEventLogs]        = useState([]);
  const [unresolvedCounts, setUnresolvedCounts] = useState({
    congested: 0, slow: 0, wrongway: 0,
  });
  const [connected,     setConnected]     = useState(false);
  // 백엔드 background fetch 성공 시 road_geo_ready 이벤트로 수신한 GeoJSON
  // null → 아직 수신 전, 객체 → 수신 완료 (MonitoringMap이 이를 감지해 도로선 렌더)
  const [serverRoadGeo, setServerRoadGeo] = useState(null);

  // camera_stream_failed 이벤트로 수신한 카메라별 실패 상태
  // { [camera_id]: { fail_count, next_retry_in, next_retry_at } }
  // camera_stream_recovered 수신 시 해당 카메라 항목이 제거된다.
  const [streamFailures, setStreamFailures] = useState({});

  const socketRef   = useRef(null);
  // 중지된 카메라 ID 집합 — 이 ID의 traffic_update는 무시 (재추가 방지)
  const stoppedRef  = useRef(new Set());
  // 콜백을 ref에 저장 — 소켓을 재생성하지 않고 항상 최신 콜백 참조
  const callbackRef = useRef(callbacks);
  useEffect(() => { callbackRef.current = callbacks; });

  // ── 이벤트 해소 처리 (조치 완료 / 조치 불필요 버튼) ──
  // reason: 'action'(조치 완료) | 'no_action'(조치 불필요)
  const resolveEvent = useCallback((eventId, reason = 'action') => {
    setEventLogs(prev =>
      prev.map(ev => ev.id === eventId ? { ...ev, is_resolved: true, resolve_reason: reason } : ev)
    );
  }, []);

  // ── select_camera emit ────────────────────────────────────
  const emitSelectCamera = useCallback((camera_id) => {
    socketRef.current?.emit('select_camera', { camera_id });
  }, []);

  // ── 소켓 연결 ──────────────────────────────────────────────
  useEffect(() => {
    if (!host) return;

    // localhost/127.0.0.1이면 http, 외부 호스트면 https 사용
    // const proto = (host.startsWith('localhost') || host.startsWith('127.')) ? 'http' : 'https';
    // const sock = io(`https://${host}`, {
    const sock = io(`http://${host}:5000`, {
      transports: ['polling', 'websocket'],
      reconnectionAttempts: 5,
      timeout: 5000,
    });
    socketRef.current = sock;

    sock.on('connect', () => {
      setConnected(true);
      // 모니터링 탭 진입을 백엔드에 알린다.
      // 백엔드는 이 SID를 _monitoring_sids에 등록하고,
      // 이전에 일시정지된 감지기가 있으면 자동으로 재개한다.
      sock.emit('monitoring_join');
    });
    sock.on('disconnect', () => setConnected(false));

    // 30프레임(약 1초)마다 수신 — 카메라별 최신 상태 갱신
    sock.on('traffic_update', (data) => {
      if (stoppedRef.current.has(data.camera_id)) return;
      setCameras(prev => {
        const prevCam  = prev[data.camera_id];
        const isActive = data.level === 'SLOW' || data.level === 'JAM';
        const wasActive = prevCam?.level === 'SLOW' || prevCam?.level === 'JAM';

        // levelSince: SLOW/JAM이 처음 시작된 시각 (ms)
        // - SMOOTH → SLOW/JAM 전환: 지금 시각 기록
        // - 이미 SLOW/JAM였으면: 기존 시각 유지
        // - SMOOTH 복귀: null 초기화
        let levelSince;
        if (!isActive) {
          levelSince = null;
        } else if (!wasActive) {
          levelSince = Date.now();
        } else {
          levelSince = prevCam?.levelSince ?? Date.now();
        }

        return { ...prev, [data.camera_id]: { ...data, levelSince } };
      });
    });

    // 정체 이상 이벤트
    sock.on('anomaly_alert', (data) => {
      setEventLogs(prev => [
        // id를 마지막에 두어 서버의 data.id가 덮어쓰는 것을 방지 (중복 key 경고 원인)
        // received_at: 클라이언트가 이벤트를 수신한 시각(ms).
        // 서버의 detected_at은 UTC 나이브 문자열이라 브라우저가 로컬 시간으로 오해석해
        // 경과 시간이 9시간(KST 오프셋)만큼 부풀려지는 버그를 막기 위해 별도 기록한다.
        { event_type: 'anomaly', is_resolved: false, ...data, id: Date.now() + Math.random(), received_at: Date.now() },
        ...prev.slice(0, 99),
      ]);
      setUnresolvedCounts(prev => ({
        ...prev,
        congested: (data.level === 'CONGESTED' || data.level === 'JAM') ? prev.congested + 1 : prev.congested,
        slow:      data.level === 'SLOW'      ? prev.slow      + 1 : prev.slow,
      }));
      callbackRef.current?.onAnomalyAlert?.(data);
    });

    // 역주행 탐지
    sock.on('wrongway_alert', (data) => {
      setEventLogs(prev => [
        // received_at: anomaly_alert 와 동일한 이유로 클라이언트 수신 시각을 기록한다.
        { event_type: 'wrongway', is_resolved: false, ...data, id: Date.now() + Math.random(), received_at: Date.now() },
        ...prev.slice(0, 99),
      ]);
      setUnresolvedCounts(prev => ({ ...prev, wrongway: prev.wrongway + 1 }));
      callbackRef.current?.onWrongwayAlert?.(data);
    });

    // 도로 선형 GeoJSON 수신 (Overpass 백그라운드 fetch 성공 시 서버가 push)
    // 폴링 없이 즉시 MonitoringMap에 도로선을 그리기 위한 이벤트
    sock.on('road_geo_ready', (data) => {
      if (data?.geo?.features?.length > 0) {
        // { geo, road } 형태로 저장 — MonitoringMap이 현재 선택된 도로와 일치할 때만 반영
        // road 필드가 없는 구버전 응답은 'gyeongbu'로 폴백
        setServerRoadGeo({ geo: data.geo, road: data.road || 'gyeongbu' });
      }
    });

    // 백엔드 MonitoringDetector가 5회 재연결 실패 후 지수 백오프 대기에 진입할 때 수신
    // fail_count: 누적 실패 횟수, next_retry_in: 다음 재시도까지 남은 초
    sock.on('camera_stream_failed', (data) => {
      setStreamFailures(prev => ({
        ...prev,
        [data.camera_id]: {
          fail_count:    data.fail_count,     // 몇 번째 실패인지
          next_retry_in: data.next_retry_in,  // 다음 재시도까지 남은 초
          next_retry_at: data.next_retry_at,  // 다음 재시도 예정 ISO 시각
          failed_at:     Date.now(),          // 클라이언트 수신 시각 (표시용)
        },
      }));
    });

    // 백엔드가 정상 프레임을 다시 받으면 실패 상태를 제거한다.
    sock.on('camera_stream_recovered', (data) => {
      setStreamFailures(prev => {
        const next = { ...prev };
        delete next[data.camera_id];   // 해당 카메라의 실패 상태 제거
        return next;
      });
    });

    // 이벤트 해소 (Step 9에서 emit — 지금은 수신만 준비)
    sock.on('resolved', (data) => {
      // camera_id 기준으로 가장 최근 미해결 이벤트 해소 처리
      setEventLogs(prev => {
        let resolved = false;
        return prev.map(ev => {
          if (!resolved && !ev.is_resolved && ev.camera_id === data.camera_id) {
            resolved = true;
            return { ...ev, is_resolved: true };
          }
          return ev;
        });
      });
      setUnresolvedCounts(prev => ({
        ...prev,
        congested: Math.max(0, prev.congested - ((data.level === 'CONGESTED' || data.level === 'JAM') ? 1 : 0)),
        slow:      Math.max(0, prev.slow      - (data.level === 'SLOW'      ? 1 : 0)),
      }));
      callbackRef.current?.onResolved?.(data);
    });

    return () => sock.close();
  }, [host]);

  // 중지된 카메라를 cameras 상태에서 즉시 제거 (시각적 피드백용)
  // 10초간 해당 camera_id의 traffic_update를 무시해 재추가 방지
  const removeCameras = useCallback((cameraIds) => {
    cameraIds.forEach(id => stoppedRef.current.add(id));
    setCameras(prev => {
      const next = { ...prev };
      cameraIds.forEach(id => delete next[id]);
      return next;
    });
    setTimeout(() => {
      cameraIds.forEach(id => stoppedRef.current.delete(id));
    }, 10000);
  }, []);

  return {
    cameras,
    eventLogs,
    unresolvedCounts,
    connected,
    emitSelectCamera,
    resolveEvent,
    removeCameras,
    serverRoadGeo,    // road_geo_ready 이벤트로 수신한 GeoJSON (null=미수신)
    streamFailures,   // { [camera_id]: { fail_count, next_retry_in, ... } } — 실패 중인 카메라 목록
  };
}
