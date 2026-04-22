import React, { useEffect, useMemo, useState } from "react";
import "./index.css";
import {
  fetchTunnelStatus,
  selectRandomCctv,
  selectCctvByName,
  setTunnelCctvList,
} from "./api";



// 발표/테스트용 고정 후보
const FIXED_CCTV_LIST = [
  {
    name: "[수도권제2순환선(봉담동탄)] 필봉산터널(동탄)",
    url: "http://cctvsec.ktict.co.kr/8327/JdqIr+tRRcj6oVvFQnzIvtzHkUDVhJZY9XY+eGNGobDo55Y5O5qOjHvT6ff9uRudnQ7jtswETvv+M/fs9ia+cqNyXt2YgXEmO36dKnPo3bg=",
  },
  {
    name: "[수도권제2순환선(봉담동탄)] 필봉산터널(봉담)",
    url: "http://cctvsec.ktict.co.kr/8326/tD+wiAbI/YfgrvESpV516dvSLQqee4qTAwt2mAYU6ROZ7nh6OHstwhRYnwIwYTgEBu1iZT4VTFyIa6Vwg+cVI3dUhm82yl2i+tDPTipVH3E=",
  },
  {
    name: "[수원광명선] 광명 구봉산터널",
    url: "http://cctvsec.ktict.co.kr/5176/kbe5SBsTXBbX0i4hdDuuSE5ZilAFwOQmPbMJch63jW/B6gwf4akV/GlpTDH8JL4t/G5lf7MncT+kRWOa3OYBqw6Z3vofjYfuMlcSlyaEZOM=",
  },
  {
    name: "[수원광명선] 수원 구봉산터널",
    url: "http://cctvsec.ktict.co.kr/5177/L9EzbfGXilhFTE5N63a8MH4UBqXrd/O8w9zGEaMHxxXrSB8CltpTYSaeQyPLaD56cv5laU25qOVvX/lysxfETzs2eLrDnmQgOnI9h6OcJD8=",
  },
];

function TunnelModule({host}){
  const [status, setStatus] = useState({
    state: "READY",
    avg_speed: 0,
    vehicle_count: 0,
    accident: false,
    lane_count: 0,
    events: [],
    event_logs: [],
    frame_id: 0,
    cctv_name: "-",
    cctv_url: "",
    dwell_times: {},
    vehicles: [],
  });

  // ---------------------------------------------------------
  // videoKey:
  // - /video-feed 요청 URL을 강제로 바꿔서 새 스트림을 요청하기 위한 키
  // - 처음에는 null로 두고, CCTV 리스트 세팅이 끝난 뒤에만 영상 요청 시작
  // ---------------------------------------------------------
  const BACKEND_URL = `http://${host}:5000`;
  // const BACKEND_URL = `https://${host}`;
  const [videoKey, setVideoKey] = useState(null);

  // ---------------------------------------------------------
  // videoLoading:
  // - 영상 연결 준비 중인지 표시
  // - true이면 "연결 중입니다..." 오버레이를 보여줌
  // - img onLoad에서 false로 바뀜
  // - img onError에서 false로 바뀌고 실패 문구를 띄움
  // ---------------------------------------------------------
  const [videoLoading, setVideoLoading] = useState(true);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // ---------------------------------------------------------
  // videoSrc:
  // - videoKey가 있을 때만 실제 /video-feed URL 생성
  // - videoKey가 null이면 영상 요청 자체를 하지 않음
  // ---------------------------------------------------------
  const videoSrc = useMemo(() => {
    if (!videoKey) return "";
    return `${BACKEND_URL}/api/tunnel/video-feed?ts=${videoKey}`;
  }, [videoKey]);

  useEffect(() => {
    let mounted = true;

    const initialize = async () => {
      try {
        // ---------------------------------------------------
        // 1) 백엔드에 고정 CCTV 후보 리스트 저장
        //    이 단계가 끝나기 전에는 video-feed를 요청하지 않음
        // ---------------------------------------------------
        await setTunnelCctvList(BACKEND_URL, FIXED_CCTV_LIST);

        // ---------------------------------------------------
        // 2) 상태 1회 읽기
        // ---------------------------------------------------
        const data = await fetchTunnelStatus(BACKEND_URL);
        if (!mounted) return;

        setStatus({
          state: data?.state ?? "READY",
          avg_speed: Number(data?.avg_speed ?? 0),
          vehicle_count: Number(data?.vehicle_count ?? 0),
          accident: Boolean(data?.accident ?? false),
          lane_count: Number(data?.lane_count ?? 0),
          events: Array.isArray(data?.events) ? data.events : [],
          event_logs: Array.isArray(data?.event_logs) ? data.event_logs : [],
          frame_id: Number(data?.frame_id ?? 0),
          cctv_name: data?.cctv_name ?? "-",
          cctv_url: data?.cctv_url ?? "",
          dwell_times: data?.dwell_times ?? {},
          vehicles: Array.isArray(data?.vehicles) ? data.vehicles : [],
        });

        // ---------------------------------------------------
        // 3) 이제서야 영상 요청 시작
        //    초반 race condition(영상 먼저 요청)을 막기 위해
        //    set-cctv-list가 끝난 뒤에만 videoKey를 세팅
        // ---------------------------------------------------
        setVideoLoading(true);
        setVideoKey(Date.now());
      } catch (err) {
        console.error("initialize error:", err);
        setVideoLoading(false);
        setError("초기 CCTV 리스트 설정 실패");
      }
    };

    const loadStatus = async () => {
      try {
        const data = await fetchTunnelStatus(BACKEND_URL);
        if (!mounted) return;

        setStatus({
          state: data?.state ?? "READY",
          avg_speed: Number(data?.avg_speed ?? 0),
          vehicle_count: Number(data?.vehicle_count ?? 0),
          accident: Boolean(data?.accident ?? false),
          lane_count: Number(data?.lane_count ?? 0),
          events: Array.isArray(data?.events) ? data.events : [],
          event_logs: Array.isArray(data?.event_logs) ? data.event_logs : [],
          frame_id: Number(data?.frame_id ?? 0),
          cctv_name: data?.cctv_name ?? "-",
          cctv_url: data?.cctv_url ?? "",
          dwell_times: data?.dwell_times ?? {},
          vehicles: Array.isArray(data?.vehicles) ? data.vehicles : [],
        });
      } catch (err) {
        console.error("status fetch error:", err);
      }
    };

    initialize();

    const timer = setInterval(loadStatus, 1000);

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  // ---------------------------------------------------------
  // sleep:
  // - 스트림 교체 직후 바로 새 요청을 보내면 기존 스트림 락과 겹칠 수 있음
  // - 그래서 랜덤선택/새로고침 뒤 잠깐 기다렸다가 videoKey를 갱신
  // ---------------------------------------------------------
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const handleRandom = async () => {
    try {
      setLoading(true);
      setError("");
      setVideoLoading(true);

      await selectRandomCctv(BACKEND_URL);

      // 기존 스트림 정리 시간을 약간 줌
      await sleep(1200);

      // 새 스트림 요청
      setVideoKey(Date.now());
    } catch (err) {
      console.error(err);
      setVideoLoading(false);
      setError("랜덤 CCTV 선택 실패");
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshVideo = async () => {
    try {
      setLoading(true);
      setError("");
      setVideoLoading(true);

      const currentName = (status.cctv_name || "").trim();

      // ---------------------------------------------------
      // 현재 선택된 CCTV가 있으면 그 이름으로 다시 선택 요청
      // 없으면 단순히 videoKey만 갱신해도 되지만,
      // 지금은 현재 CCTV 기준으로 재연결을 시도
      // ---------------------------------------------------
      if (currentName && currentName !== "-") {
        await selectCctvByName(BACKEND_URL, currentName);
        await sleep(1200);
      }

      setVideoKey(Date.now());
    } catch (err) {
      console.error("refresh video error:", err);
      setVideoLoading(false);
      setError("영상 새로고침 실패");
    } finally {
      setLoading(false);
    }
  };

  const stateClass = getStateClass(status.state);

  return (
    <div className="smart-page">
      <main className="smart-main">
        <section className="panel panel-header">
          <div className="panel-header-left">
            <div className="panel-title">🚨 스마트 터널 시스템</div>
            <div className="panel-subtitle">{status.cctv_name || "-"}</div>
          </div>

          <div className="panel-header-right">
            <button
              className="action-btn"
              onClick={handleRandom}
              disabled={loading}
            >
              랜덤 선택
            </button>
            <button
              className="action-btn"
              onClick={handleRefreshVideo}
              disabled={loading}
            >
              영상 새로고침
            </button>
          </div>
        </section>

        {loading && <div className="top-notice">처리 중...</div>}
        {error && <div className="top-error">{error}</div>}

        <section className="top-grid">
          <div className="panel panel-video">
            <div className="section-title">📹 CCTV</div>

            <div className="video-wrap">
              {/* ---------------------------------------------
                  연결 중 오버레이
                  - 영상 준비 중일 때 먼저 보여줌
                  - 초반 실패처럼 보이지 않게 UX 개선
                 --------------------------------------------- */}
              {videoLoading && (
                <div className="video-overlay-message">
                  연결 중입니다...
                </div>
              )}

              {/* ---------------------------------------------
                  videoKey가 있을 때만 영상 요청
                  - 초기 렌더 때는 videoKey=null 이므로 요청 안 나감
                  - set-cctv-list 완료 후에만 영상 시작
                 --------------------------------------------- */}
              {videoKey && (
                <img
                  key={videoKey}
                  src={videoSrc}
                  alt="cctv"
                  className="video-image"
                  onLoad={() => {
                    // 영상이 실제로 브라우저에 로드되면 연결중 문구 제거
                    setVideoLoading(false);
                    setError("");
                  }}
                  onError={() => {
                    // 진짜 실패한 경우에만 실패 문구 표시
                    setVideoLoading(false);
                    setError("영상 스트리밍 연결 실패");
                  }}
                />
              )}
            </div>

            <div className="video-caption">{status.cctv_name || "-"}</div>
          </div>

          <div className="panel panel-status">
            <div className="section-title">🚦 상태</div>

            <div className={`state-badge ${stateClass}`}>
              {status.state}
            </div>

            <div className="status-block">
              <div className="status-label">⚡ 평균 속도</div>
              <div className="status-value">
                {status.avg_speed.toFixed(2)} px/s
              </div>
            </div>

            <div className="status-mini-box">
              <div>Frame ID: {status.frame_id}</div>
              <div>차량 수: {status.vehicle_count}</div>
              <div>차선 수: {status.lane_count}</div>
              <div>사고 여부: {status.accident ? "True" : "False"}</div>
            </div>

            <div className="divider" />

            <div className="section-subtitle">📌 이벤트 로그</div>
            <div className="event-log scrollable-log">
              {status.event_logs && status.event_logs.length > 0 ? (
                status.event_logs
                  .slice()
                  .reverse()
                  .map((event, idx) => (
                    <div key={`${event}-${idx}`} className="event-item">
                      {event}
                    </div>
                  ))
              ) : status.events.length > 0 ? (
                status.events.map((event, idx) => (
                  <div key={`${event}-${idx}`} className="event-item">
                    {event}
                  </div>
                ))
              ) : (
                <div className="event-empty">이상 징후 없음 (정상 흐름 유지)</div>
              )}
            </div>
          </div>
        </section>

        <section className="bottom-grid">
          <div className="panel panel-chart">
            <div className="section-title">📊 차량 속도 (ROI)</div>
            <div className="chart-summary">총 차량 수 {status.vehicle_count}</div>

            <div className="chart-placeholder">
              <div className="axis axis-y" />
              <div className="axis axis-x" />

              {status.vehicles.slice(0, 6).map((v, idx) => (
                <div
                  key={idx}
                  className="chart-bar"
                  style={{
                    left: `${70 + idx * 50}px`,
                    height: `${Math.max(20, Math.min(140, (v.speed || 0) * 8))}px`,
                  }}
                  title={`ID:${v.id} / speed:${v.speed}`}
                />
              ))}
            </div>
          </div>

          <div className="panel panel-chart">
            <div className="section-title">📊 체류시간</div>
            <div className="chart-summary">
              평균 체류시간: {calcAvgDwell(status.dwell_times)} sec
            </div>

            <div className="chart-placeholder">
              <div className="axis axis-y" />
              <div className="axis axis-x" />

              {Object.entries(status.dwell_times)
                .slice(0, 6)
                .map(([id, time], idx) => (
                  <div
                    key={id}
                    className="chart-bar green"
                    style={{
                      left: `${70 + idx * 50}px`,
                      height: `${Math.max(20, Math.min(140, Number(time) * 8))}px`,
                    }}
                    title={`ID:${id} / dwell:${time}`}
                  />
                ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function getStateClass(state) {
  if (state === "NORMAL") return "normal";
  if (state === "CONGESTION") return "congestion";
  if (state === "JAM") return "jam";
  return "ready";
}

function calcAvgDwell(dwellTimes) {
  const values = Object.values(dwellTimes || {})
    .map(Number)
    .filter((v) => !Number.isNaN(v));

  if (values.length === 0) return "0.00";

  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  return avg.toFixed(2);
}

export default TunnelModule;