import React, { useEffect, useMemo, useRef, useState } from "react";
import "./index.css";
import {
  fetchTunnelStatus,
  fetchTunnelCctvUrl,
  selectRandomCctv,
  selectCctvByName,
} from "./api";

/* =========================================================
 * 평균속도 -> 현실 속도 설명
 * ========================================================= */
function getSpeedHintText(avgSpeed) {
  const speed = Number(avgSpeed || 0);

  if (speed <= 1.3) {
    return "실제속도 30km/h 이하 추정";
  }
  if (speed <= 2.6) {
    return "실제속도 30km/h 초과 ~ 50km/h 이하 추정";
  }
  return "실제속도 50km/h 이상 추정";
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

/* =========================================================
 * 환기 위험도 표시
 * ========================================================= */
function getVentRiskLabel(level) {
  if (level === "NORMAL") return "🟢 정상";
  if (level === "CAUTION") return "🟡 주의";
  if (level === "WARNING") return "🟠 경고";
  if (level === "DANGER") return "🔴 위험";
  return "⚪ 미정";
}

function getVentRiskClass(level) {
  if (level === "NORMAL") return "vent-normal";
  if (level === "CAUTION") return "vent-caution";
  if (level === "WARNING") return "vent-warning";
  if (level === "DANGER") return "vent-danger";
  return "vent-normal";
}

function TunnelModule({ host }) {
  const [status, setStatus] = useState({
    state: "READY",
    avg_speed: 0,
    avg_speed_roi: 0,
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
    vehicles_in_roi: [],
    lane_reestimate_status: "idle",
    lane_reestimate_frame_count: 0,
    lane_reestimate_window: 50,
    minute_vehicle_count: 0,
    ventilation: {
      risk_score_base: 0,
      risk_score_final: 0,
      risk_level: "NORMAL",
      alarm: false,
      message: "공기질 상태 정상",
      vehicle_count_roi: 0,
      weighted_vehicle_count: 0,
      traffic_density: 0,
      avg_dwell_time_roi: 0,
      avg_speed_roi: 0,
    },
  });

  const BACKEND_URL = `http://${host}:5000`;
  const [videoKey, setVideoKey] = useState(null);
  const [videoLoading, setVideoLoading] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reestimateLoading, setReestimateLoading] = useState(false);

  const prevVentLevelRef = useRef("NORMAL");

  const videoSrc = useMemo(() => {
    if (!videoKey) return "";
    return `${BACKEND_URL}/api/tunnel/video-feed?ts=${videoKey}`;
  }, [videoKey, BACKEND_URL]);

  const speedHintText = useMemo(() => {
    return getSpeedHintText(status.avg_speed);
  }, [status.avg_speed]);

  const laneReestimateText = useMemo(() => {
    return getLaneReestimateText(status);
  }, [
    status.lane_reestimate_status,
    status.lane_reestimate_frame_count,
    status.lane_reestimate_window,
  ]);

  const vent = status.ventilation || {};
  const ventRiskLabel = useMemo(
    () => getVentRiskLabel(vent.risk_level),
    [vent.risk_level]
  );
  const ventRiskClass = useMemo(
    () => getVentRiskClass(vent.risk_level),
    [vent.risk_level]
  );

  const applyStatusData = (data) => {
    setStatus({
      state: data?.state ?? "READY",
      avg_speed: Number(data?.avg_speed ?? 0),
      avg_speed_roi: Number(data?.avg_speed_roi ?? 0),
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
      vehicles_in_roi: Array.isArray(data?.vehicles_in_roi) ? data.vehicles_in_roi : [],
      lane_reestimate_status: data?.lane_reestimate_status ?? "idle",
      lane_reestimate_frame_count: Number(data?.lane_reestimate_frame_count ?? 0),
      lane_reestimate_window: Number(data?.lane_reestimate_window ?? 50),
      minute_vehicle_count: Number(data?.minute_vehicle_count ?? 0),
      ventilation: data?.ventilation ?? {
        risk_score_base: 0,
        risk_score_final: 0,
        risk_level: "NORMAL",
        alarm: false,
        message: "공기질 상태 정상",
        vehicle_count_roi: 0,
        weighted_vehicle_count: 0,
        traffic_density: 0,
        avg_dwell_time_roi: 0,
        avg_speed_roi: 0,
      },
    });
  };

  useEffect(() => {
    let mounted = true;

    const initialize = async () => {
      try {
        const cctvRes = await fetchTunnelCctvUrl(host);

        if (!cctvRes?.ok || !Array.isArray(cctvRes?.items) || cctvRes.items.length === 0) {
          throw new Error("CCTV 리스트를 불러오지 못했습니다.");
        }

        const data = await fetchTunnelStatus(BACKEND_URL);
        if (!mounted) return;

        applyStatusData(data);
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
        applyStatusData(data);
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
  }, [BACKEND_URL, host]);

  useEffect(() => {
    const currentLevel = status?.ventilation?.risk_level || "NORMAL";
    const prevLevel = prevVentLevelRef.current;

    if (currentLevel === "DANGER" && prevLevel !== "DANGER") {
      alert("🔴 공기질 위험 단계입니다.\n환기 대응 조치가 필요합니다.");
    }

    prevVentLevelRef.current = currentLevel;
  }, [status?.ventilation?.risk_level]);

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

      if (!data?.ok) {
        setError(data?.message || "차선 재추정 요청 실패");
        return;
      }

      const refreshed = await fetchTunnelStatus(BACKEND_URL);
      applyStatusData(refreshed);
    } catch (err) {
      console.error("lane reestimate error:", err);
      setError("차선 재추정 요청 실패");
    } finally {
      setReestimateLoading(false);
    }
  };

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
              랜덤선택
            </button>

            <button
              className="action-btn"
              onClick={handleRefreshVideo}
              disabled={loading}
            >
              영상새로고침
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
            <div className="section-title">🚦 교통흐름 상태</div>

            <div className={`state-badge ${stateClass}`}>
              {status.state}
            </div>

            <div className="status-speed-line">
              <span className="status-speed-main">
                평균속도 : {status.avg_speed.toFixed(2)} px/s
              </span>
              <span className="status-speed-sub">
                ({speedHintText})
              </span>
            </div>

            <div className="traffic-summary-grid">
              <div className="summary-card">
                <div className="summary-card-label">차선수</div>
                <div className="summary-card-value">{status.lane_count}차선</div>
              </div>

              <div className="summary-card">
                <div className="summary-card-label">차선재추정</div>
                <div className="summary-card-value small">{laneReestimateText}</div>
                <button
                  className="summary-mini-btn"
                  onClick={handleLaneReestimate}
                  disabled={reestimateLoading}
                >
                  {reestimateLoading ? "요청중..." : "재추정"}
                </button>
              </div>

              <div className="summary-card">
                <div className="summary-card-label">차선저장</div>
                <div className="summary-card-value small">현재 차선 메모리</div>
                <button
                  className="summary-mini-btn secondary"
                  onClick={handleLaneSave}
                >
                  저장
                </button>
              </div>
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

        <section className="panel panel-air">
          <div className="panel-air-header">
            <div className="section-title">🌫️ 터널 공기질 상태</div>
            <div className="section-title air-divider-title">|</div>
            <div className="section-title">환기대응정보(ROI)</div>
          </div>

          <div className="air-grid">
            <div className="air-left">
              <div className={`vent-risk-card ${ventRiskClass}`}>
                <div className="vent-risk-label">{ventRiskLabel}</div>
                <div className="vent-risk-score">
                  위험 점수: {Number(vent.risk_score_final ?? 0).toFixed(2)}
                </div>
                <div className="vent-risk-alarm">
                  알람 상태: {vent.alarm ? "ON" : "OFF"}
                </div>
              </div>

              <div className="vent-gauge">
                <div
                  className="vent-gauge-fill"
                  style={{
                    width: `${Math.min(
                      100,
                      Math.max(0, Number(vent.risk_score_final ?? 0) * 100)
                    )}%`,
                  }}
                />
              </div>

              <div className="vent-step-legend">
                <span>🟢 정상</span>
                <span>🟡 주의</span>
                <span>🟠 경고</span>
                <span>🔴 위험</span>
              </div>

              <div className="vent-message">
                {vent.message || "공기질 상태 정상"}
              </div>
            </div>

            <div className="air-right">
              <div className="vent-table">
                <div className="vent-row">
                  <span className="vent-key">차량 수</span>
                  <span className="vent-value">{vent.vehicle_count_roi ?? 0}대</span>
                </div>

                <div className="vent-row">
                  <span className="vent-key">평균속도</span>
                  <span className="vent-value">
                    {Number(vent.avg_speed_roi ?? status.avg_speed_roi ?? 0).toFixed(2)} px/s
                  </span>
                </div>

                <div className="vent-row">
                  <span className="vent-key">교통밀도</span>
                  <span className="vent-value">
                    {Number(vent.traffic_density ?? 0).toFixed(2)}
                  </span>
                </div>

                <div className="vent-row">
                  <span className="vent-key">평균 체류시간</span>
                  <span className="vent-value">
                    {Number(vent.avg_dwell_time_roi ?? 0).toFixed(2)} sec
                  </span>
                </div>
              </div>
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

export default TunnelModule;