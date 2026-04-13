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
  const [connected, setConnected] = useState(false);

  const socketRef   = useRef(null);
  // 콜백을 ref에 저장 — 소켓을 재생성하지 않고 항상 최신 콜백 참조
  const callbackRef = useRef(callbacks);
  useEffect(() => { callbackRef.current = callbacks; });

  // ── 이벤트 해소 처리 (경보 해제 버튼 or resolved 소켓 이벤트) ──
  const resolveEvent = useCallback((eventId) => {
    setEventLogs(prev =>
      prev.map(ev => ev.id === eventId ? { ...ev, is_resolved: true } : ev)
    );
  }, []);

  // ── select_camera emit ────────────────────────────────────
  const emitSelectCamera = useCallback((camera_id) => {
    socketRef.current?.emit('select_camera', { camera_id });
  }, []);

  // ── 소켓 연결 ──────────────────────────────────────────────
  useEffect(() => {
    if (!host) return;

    const sock = io(`http://${host}:5000`, {
      transports: ['polling', 'websocket'],
      reconnectionAttempts: 5,
      timeout: 5000,
    });
    socketRef.current = sock;

    sock.on('connect',    () => setConnected(true));
    sock.on('disconnect', () => setConnected(false));

    // 30프레임(약 1초)마다 수신 — 카메라별 최신 상태 갱신
    sock.on('traffic_update', (data) => {
      setCameras(prev => ({ ...prev, [data.camera_id]: data }));
    });

    // 정체 이상 이벤트
    sock.on('anomaly_alert', (data) => {
      setEventLogs(prev => [
        { id: Date.now() + Math.random(), event_type: 'anomaly', is_resolved: false, ...data },
        ...prev.slice(0, 99),
      ]);
      setUnresolvedCounts(prev => ({
        ...prev,
        congested: data.level === 'CONGESTED' ? prev.congested + 1 : prev.congested,
        slow:      data.level === 'SLOW'      ? prev.slow      + 1 : prev.slow,
      }));
      callbackRef.current?.onAnomalyAlert?.(data);
    });

    // 역주행 탐지
    sock.on('wrongway_alert', (data) => {
      setEventLogs(prev => [
        { id: Date.now() + Math.random(), event_type: 'wrongway', is_resolved: false, ...data },
        ...prev.slice(0, 99),
      ]);
      setUnresolvedCounts(prev => ({ ...prev, wrongway: prev.wrongway + 1 }));
      callbackRef.current?.onWrongwayAlert?.(data);
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
        congested: Math.max(0, prev.congested - (data.level === 'CONGESTED' ? 1 : 0)),
        slow:      Math.max(0, prev.slow      - (data.level === 'SLOW'      ? 1 : 0)),
      }));
      callbackRef.current?.onResolved?.(data);
    });

    return () => sock.close();
  }, [host]);

  return {
    cameras,
    eventLogs,
    unresolvedCounts,
    connected,
    emitSelectCamera,
    resolveEvent,
  };
}
