import React, { useEffect, useMemo, useState } from "react";
import "./index.css";
import {
  fetchTunnelStatus,
  selectRandomCctv,
  selectCctvByName,
  setTunnelCctvList,
} from "./api";

const BACKEND_URL = "http://localhost:5000";

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

function TunnelModule() {
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

  const [keyword, setKeyword] = useState("필봉산터널(동탄)");
  const [videoKey, setVideoKey] = useState(Date.now());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const videoSrc = useMemo(() => {
    return `${BACKEND_URL}/api/tunnel/video-feed?ts=${videoKey}`;
  }, [videoKey]);

  useEffect(() => {
    let mounted = true;

    const initialize = async () => {
      try {
        await setTunnelCctvList(BACKEND_URL, FIXED_CCTV_LIST);

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
        console.error("initialize error:", err);
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

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const handleRandom = async () => {
    try {
      setLoading(true);
      setError("");

      await selectRandomCctv(BACKEND_URL);
      await sleep(1200);
      setVideoKey(Date.now());
    } catch (err) {
      console.error(err);
      setError("랜덤 CCTV 선택 실패");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectByName = async () => {
    try {
      setLoading(true);
      setError("");

      await selectCctvByName(BACKEND_URL, keyword);
      await sleep(1200);
      setVideoKey(Date.now());
    } catch (err) {
      console.error(err);
      setError("이름으로 CCTV 선택 실패");
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshVideo = async () => {
    try {
      setLoading(true);
      setError("");

      const currentName = (status.cctv_name || "").trim();

      if (currentName && currentName !== "-") {
        await selectCctvByName(BACKEND_URL, currentName);
      } else if (keyword.trim()) {
        await selectCctvByName(BACKEND_URL, keyword.trim());
      } else {
        await selectRandomCctv(BACKEND_URL);
      }

      await sleep(1200);
      setVideoKey(Date.now());
    } catch (err) {
      console.error("refresh video error:", err);
      setError("영상 새로고침 실패");
    } finally {
      setLoading(false);
    }
  };

  const stateClass = getStateClass(status.state);

  return (
    <div className="smart-page">
      <aside className="smart-sidebar">
        <div className="sidebar-logo">
          <div className="logo-box">T</div>
          <div>
            <div className="logo-title">TADS</div>
            <div className="logo-sub">관제 시스템</div>
          </div>
        </div>

        <div className="sidebar-menu-title">메인 메뉴</div>

        <nav className="sidebar-menu">
          <button className="sidebar-item">CCTV 모니터링</button>
          <button className="sidebar-item">교통 정체 흐름</button>
          <button className="sidebar-item active">스마트 터널 시스템</button>
          <button className="sidebar-item">번호판 인식</button>
          <button className="sidebar-item">라즈베리파이 CCTV</button>
          <button className="sidebar-item">통계 데이터</button>
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-status">● 시스템 온라인</div>
          <button className="logout-btn">로그아웃</button>
        </div>
      </aside>

      <main className="smart-main">
        <section className="panel panel-header">
          <div className="panel-header-left">
            <div className="panel-title">🚨 스마트 터널 시스템</div>
          </div>

          <div className="panel-header-right">
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="예: 필봉산터널(동탄)"
              className="search-input"
            />
            <button
              className="action-btn primary"
              onClick={handleSelectByName}
              disabled={loading}
            >
              이름 선택
            </button>
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
              <img
                key={videoKey}
                src={videoSrc}
                alt="cctv"
                className="video-image"
                onError={() => setError("영상 스트리밍 연결 실패")}
              />
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
            <div className="event-log">
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