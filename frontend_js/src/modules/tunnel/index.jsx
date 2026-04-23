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


/* =========================================================
 * 평균속도 -> 현실 속도 설명
 * ========================================================= */
function getSpeedHintText(avgSpeed) {
  const speed = Number(avgSpeed || 0);

  if (speed <= 1.3) {
    return "실제속도 : 30km/h 이하 추정";
  }
  if (speed <= 2.6) {
    return "실제속도 : 30km/h 초과 ~ 50km/h 이하 추정";
  }
  return "실제속도 : 50km/h 이상 추정";
}

/* =========================================================
 * 차선 재추정 상태 문자열
 * ========================================================= */
function getLaneReestimateText(status) {
  const s = status?.lane_reestimate_status || "idle";
  const count = Number(status?.lane_reestimate_frame_count || 0);
  const total = Number(status?.lane_reestimate_window || 50);

  if (s === "reestimating") return `재추정 중 (${count}/${total})`;
  if (s === "reestimated") return "재추정 완료";
  if (s === "confirmed") return "확정";
  return "대기";
}

const handleLaneSave = async () => {
  try {
    setError("");

    const res = await fetch(`${BACKEND_URL}/api/tunnel/lane/save`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });

    const data = await res.json();

    if (!data?.ok) {
      setError(data?.message || "차선 저장 실패");
      return;
    }

    alert("현재 차선을 저장했습니다.");
  } catch (err) {
    console.error("lane save error:", err);
    setError("차선 저장 요청 실패");
  }
};

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

    // [추가] 차선 재추정 상태
    lane_reestimate_status: "idle",
    lane_reestimate_frame_count: 0,
    lane_reestimate_window: 50,

    // [추가] 최근 1분 누적 차량수
    minute_vehicle_count: 0,
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
  // ---------------------------------------------------------
  const [videoLoading, setVideoLoading] = useState(true);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reestimateLoading, setReestimateLoading] = useState(false);

  // ---------------------------------------------------------
  // videoSrc:
  // ---------------------------------------------------------
  const videoSrc = useMemo(() => {
    if (!videoKey) return "";
    return `${BACKEND_URL}/api/tunnel/video-feed?ts=${videoKey}`;
  }, [videoKey]);

  // ---------------------------------------------------------
  // 속도 설명 문자열
  // ---------------------------------------------------------
  const speedHintText = useMemo(() => {
    return getSpeedHintText(status.avg_speed);
  }, [status.avg_speed]);

  // ---------------------------------------------------------
  // 차선 재추정 상태 문자열
  // ---------------------------------------------------------
  const laneReestimateText = useMemo(() => {
    return getLaneReestimateText(status);
  }, [
    status.lane_reestimate_status,
    status.lane_reestimate_frame_count,
    status.lane_reestimate_window,
  ]);

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
          lane_reestimate_status: data?.lane_reestimate_status ?? "idle",
          lane_reestimate_frame_count: Number(data?.lane_reestimate_frame_count ?? 0),
          lane_reestimate_window: Number(data?.lane_reestimate_window ?? 50),
          minute_vehicle_count: Number(data?.minute_vehicle_count ?? 0),
        });

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
          lane_reestimate_status: data?.lane_reestimate_status ?? "idle",
          lane_reestimate_frame_count: Number(data?.lane_reestimate_frame_count ?? 0),
          lane_reestimate_window: Number(data?.lane_reestimate_window ?? 50),
          minute_vehicle_count: Number(data?.minute_vehicle_count ?? 0),
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
  // ---------------------------------------------------------
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const handleRandom = async () => {
    try {
      setLoading(true);
      setError("");
      setVideoLoading(true);

      await selectRandomCctv(BACKEND_URL);
      await sleep(1200);
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

  // ---------------------------------------------------------
  // [추가] 차선 재추정 버튼
  // ---------------------------------------------------------
  const handleLaneReestimate = async () => {
    try {
      setReestimateLoading(true);
      setError("");

      const res = await fetch(`${BACKEND_URL}/api/tunnel/lane/reestimate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      const data = await res.json();
      console.log("lane reestimate response:", data);

      if (!data?.ok) {
        setError(data?.message || "차선 재추정 요청 실패");
        return;
      }

      // 버튼 누른 직후 상태 한 번 갱신
      const refreshed = await fetchTunnelStatus(BACKEND_URL);
      setStatus({
        state: refreshed?.state ?? "READY",
        avg_speed: Number(refreshed?.avg_speed ?? 0),
        vehicle_count: Number(refreshed?.vehicle_count ?? 0),
        accident: Boolean(refreshed?.accident ?? false),
        lane_count: Number(refreshed?.lane_count ?? 0),
        events: Array.isArray(refreshed?.events) ? refreshed.events : [],
        event_logs: Array.isArray(refreshed?.event_logs) ? refreshed.event_logs : [],
        frame_id: Number(refreshed?.frame_id ?? 0),
        cctv_name: refreshed?.cctv_name ?? "-",
        cctv_url: refreshed?.cctv_url ?? "",
        dwell_times: refreshed?.dwell_times ?? {},
        vehicles: Array.isArray(refreshed?.vehicles) ? refreshed.vehicles : [],
        lane_reestimate_status: refreshed?.lane_reestimate_status ?? "idle",
        lane_reestimate_frame_count: Number(refreshed?.lane_reestimate_frame_count ?? 0),
        lane_reestimate_window: Number(refreshed?.lane_reestimate_window ?? 50),
        minute_vehicle_count: Number(refreshed?.minute_vehicle_count ?? 0),
      });
    } catch (err) {
      console.error("lane reestimate error:", err);
      setError("차선 재추정 요청 실패");
    } finally {
      setReestimateLoading(false);
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

            {/* [추가] 차선 재추정 버튼 */}
            <button
              className="action-btn"
              onClick={handleLaneReestimate}
              disabled={reestimateLoading}
            >
              {reestimateLoading ? "재추정 요청중..." : "차선 재추정"}
            </button>
            
            <button
              className="action-btn"
              onClick={handleLaneSave}
            >
              차선 저장
            </button>

          </div>
        </section>

        {loading && <div className="top-notice">처리 중...</div>}
        {error && <div className="top-error">{error}</div>}

        <section className="top-grid">
          <div className="panel panel-video">
            <div className="section-title">📹 CCTV</div>

            <div className="video-wrap">
              {videoLoading && (
                <div className="video-overlay-message">
                  연결 중입니다...
                </div>
              )}

              {videoKey && (
                <img
                  key={videoKey}
                  src={videoSrc}
                  alt="cctv"
                  className="video-image"
                  onLoad={() => {
                    setVideoLoading(false);
                    setError("");
                  }}
                  onError={() => {
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

              {/* [추가] 현실 속도 설명 */}
              <div
                style={{
                  marginTop: "6px",
                  fontSize: "13px",
                  color: "#cbd5e1",
                  lineHeight: "1.4",
                }}
              >
                ({speedHintText})
              </div>
            </div>

            {/* [수정] 카드형 표시판 */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, 1fr)",
                gap: "10px",
                marginTop: "14px",
                marginBottom: "14px",
              }}
            >
              <div
                style={{
                  background: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "10px",
                  padding: "12px 8px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: "12px", color: "#9ca3af", marginBottom: "6px" }}>
                  차선수
                </div>
                <div style={{ fontSize: "20px", fontWeight: "700", color: "#f9fafb" }}>
                  {status.lane_count}차선
                </div>
              </div>

              <div
                style={{
                  background: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "10px",
                  padding: "12px 8px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: "12px", color: "#9ca3af", marginBottom: "6px" }}>
                  차량 수
                </div>
                <div style={{ fontSize: "20px", fontWeight: "700", color: "#f9fafb" }}>
                  {status.vehicle_count}대
                </div>
              </div>

              <div
                style={{
                  background: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "10px",
                  padding: "12px 8px",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: "12px", color: "#9ca3af", marginBottom: "6px" }}>
                  누적 차량수(1분)
                </div>
                <div style={{ fontSize: "20px", fontWeight: "700", color: "#f9fafb" }}>
                  {status.minute_vehicle_count}대
                </div>
              </div>
            </div>

            {/* [수정] 사고 여부 제거, 차선 재추정 상태 표시 */}
            <div className="status-mini-box">
              <div>Frame ID: {status.frame_id}</div>
              <div>차선 재추정: {laneReestimateText}</div>
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
  if (state === "ERROR") return "jam";
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