import React, { useEffect, useMemo, useRef, useState } from "react";
import "./index.css";
import {
  fetchTunnelStatus,
  fetchTunnelCctvUrl,
  selectRandomCctv,
  stopTunnelStream,
  restartTunnelStreamRandom,
} from "./api";

/* =========================================================
 * 공통 유틸
 * ========================================================= */
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const clamp01 = (value) => clamp(Number(value || 0), 0, 1);

function getSpeedHintText(avgSpeed) {
  const speed = Number(avgSpeed || 0);

  if (speed <= 1.3) return "실제속도 30km/h 이하 추정";
  if (speed <= 2.6) return "실제속도 30~50km/h 추정";
  return "실제속도 50km/h 이상 추정";
}

function getLaneReestimateText(status) {
  const s = status?.lane_reestimate_status || "idle";
  const count = Number(status?.lane_reestimate_frame_count || 0);
  const total = Number(status?.lane_reestimate_window || 50);

  if (s === "reestimating") return `재추정 중 (${count}/${total})`;
  if (s === "reestimated") return "재추정 완료";
  if (s === "confirmed") return "확정";
  return "대기";
}

function getStateClass(state) {
  if (state === "NORMAL") return "normal";
  if (state === "CONGESTION") return "congestion";
  if (state === "JAM") return "jam";
  if (state === "ACCIDENT") return "accident";
  if (state === "ERROR") return "error";
  return "ready";
}

function getVentRiskInfo(level) {
  switch (level) {
    case "NORMAL":
      return { label: "정상", emoji: "🟢", className: "risk-normal" };
    case "CAUTION":
      return { label: "주의", emoji: "🟡", className: "risk-caution" };
    case "WARNING":
      return { label: "경고", emoji: "🟠", className: "risk-warning" };
    case "DANGER":
      return { label: "위험", emoji: "🔴", className: "risk-danger" };
    default:
      return { label: "정상", emoji: "🟢", className: "risk-normal" };
  }
}

function getRiskLevelByScore(score) {
  const s = Number(score || 0);

  if (s >= 0.85) return "DANGER";
  if (s >= 0.6) return "WARNING";
  if (s >= 0.35) return "CAUTION";
  return "NORMAL";
}

function getAirMessage(level) {
  switch (level) {
    case "NORMAL":
      return "공기질 상태 정상";
    case "CAUTION":
      return "공기질 주의 단계";
    case "WARNING":
      return "공기질 경고 단계";
    case "DANGER":
      return "환기 대응 필요";
    default:
      return "공기질 상태 정상";
  }
}

/* =========================================================
 * 현재 상태가 유지된다고 가정한 5분 후 추정치
 * - 프론트 표시용 추정값
 * ========================================================= */
function buildFutureVentPreview(vent, status) {
  const currentScore = clamp01(vent?.risk_score_final ?? 0);
  const density = Number(vent?.traffic_density ?? 0);
  const dwell = Number(vent?.avg_dwell_time_roi ?? 0);
  const avgSpeed = Number(vent?.avg_speed_roi ?? status?.avg_speed_roi ?? 0);
  const vehicleCount = Number(vent?.vehicle_count_roi ?? 0);
  const trafficState = String(status?.state || "NORMAL").toUpperCase();
  const accident = Boolean(status?.accident);

  let stateBonus = 0.04;
  if (trafficState === "CONGESTION") stateBonus = 0.10;
  if (trafficState === "JAM") stateBonus = 0.18;
  if (trafficState === "ACCIDENT" || accident) stateBonus = 0.22;

  const lowSpeedBonus =
    avgSpeed <= 1.2 ? 0.12 : avgSpeed <= 2.0 ? 0.08 : avgSpeed <= 3.0 ? 0.04 : 0.01;

  const densityBonus = density * 0.12;
  const dwellBonus = clamp(dwell / 60, 0, 1) * 0.10;

  const predictedScore = clamp01(
    currentScore + stateBonus + lowSpeedBonus + densityBonus + dwellBonus
  );

  const predictedLevel = getRiskLevelByScore(predictedScore);

  const predictedVehicleCount = Math.max(
    0,
    Math.round(
      trafficState === "NORMAL"
        ? vehicleCount
        : trafficState === "CONGESTION"
        ? vehicleCount * 1.05
        : trafficState === "JAM"
        ? vehicleCount * 1.12
        : vehicleCount * 1.15
    )
  );

  const predictedSpeed = Math.max(
    0,
    trafficState === "NORMAL"
      ? avgSpeed * 0.98
      : trafficState === "CONGESTION"
      ? avgSpeed * 0.92
      : trafficState === "JAM"
      ? avgSpeed * 0.82
      : avgSpeed * 0.75
  );

  const predictedDensity = clamp(
    trafficState === "NORMAL"
      ? density + 0.02
      : trafficState === "CONGESTION"
      ? density + 0.05
      : trafficState === "JAM"
      ? density + 0.08
      : density + 0.10,
    0,
    1.5
  );

  const predictedDwell = Math.max(
    0,
    trafficState === "NORMAL"
      ? dwell * 1.05
      : trafficState === "CONGESTION"
      ? dwell * 1.12
      : trafficState === "JAM"
      ? dwell * 1.22
      : dwell * 1.30
  );

  return {
    risk_score_final: predictedScore,
    risk_level: predictedLevel,
    message: getAirMessage(predictedLevel),
    vehicle_count_roi: predictedVehicleCount,
    avg_speed_roi: predictedSpeed,
    traffic_density: predictedDensity,
    avg_dwell_time_roi: predictedDwell,
  };
}

/* =========================================================
 * 공기질 위험 게이지 공통 컴포넌트
 * ========================================================= */
function AirQualityGauge({ level, score }) {
  const safeScore = clamp01(score);
  const left = `${safeScore * 100}%`;

  return (
    <div className="air-gauge-wrap modern">
      <div className="air-gauge-label-row">
        <span className={level === "NORMAL" ? "active" : ""}>정상</span>
        <span className={level === "CAUTION" ? "active" : ""}>주의</span>
        <span className={level === "WARNING" ? "active" : ""}>경고</span>
        <span className={level === "DANGER" ? "active" : ""}>위험</span>
      </div>

      <div className="air-gauge-track">
        <div className="air-gauge-segment seg-normal" />
        <div className="air-gauge-segment seg-caution" />
        <div className="air-gauge-segment seg-warning" />
        <div className="air-gauge-segment seg-danger" />
        <div className="air-gauge-thumb" style={{ left }} />
      </div>
    </div>
  );
}

function AirMetricCard({ label, value, unit = "" }) {
  return (
    <div className="air-metric-card modern">
      <div className="air-metric-label">{label}</div>
      <div className="air-metric-value">
        {value}
        <span className="air-metric-unit">{unit}</span>
      </div>
    </div>
  );
}

function AirPanel({ title, subtitle, ventData, showForecastBadge = false }) {
  const riskInfo = getVentRiskInfo(ventData?.risk_level);
  const safeScore = clamp01(ventData?.risk_score_final ?? 0);

  return (
    <div className="air-half-panel modern">
      <div className="air-half-header modern">
        <div>
          <div className="air-half-title">{title}</div>
          <div className="air-half-subtitle">{subtitle}</div>
        </div>

        <div className={`air-status-chip modern ${riskInfo.className}`}>
          <span className="air-status-dot" />
          <span className="air-status-text">{riskInfo.label}</span>
          {showForecastBadge && <span className="air-status-badge">예측</span>}
        </div>
      </div>

      <div className="air-score-row">
        <div className="air-score-label">위험 점수</div>
        <div className="air-score-value">{safeScore.toFixed(2)}</div>
      </div>

      <AirQualityGauge level={ventData?.risk_level} score={safeScore} />

      <div className="air-metrics-grid modern">
        <AirMetricCard
          label="차량수"
          value={Number(ventData?.vehicle_count_roi ?? 0)}
          unit="대"
        />
        <AirMetricCard
          label="평균속도"
          value={Number(ventData?.avg_speed_roi ?? 0).toFixed(2)}
          unit=" px/s"
        />
        <AirMetricCard
          label="교통밀도"
          value={Number(ventData?.traffic_density ?? 0).toFixed(2)}
        />
        <AirMetricCard
          label="평균체류시간"
          value={Number(ventData?.avg_dwell_time_roi ?? 0).toFixed(2)}
          unit=" sec"
        />
      </div>

      <div className="air-message-line modern">
        {ventData?.message || "공기질 상태 정상"}
      </div>
    </div>
  );
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

  const [cctvSource, setCctvSource] = useState("");
  const [videoKey, setVideoKey] = useState(null);
  const [videoLoading, setVideoLoading] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reestimateLoading, setReestimateLoading] = useState(false);

  const BACKEND_URL = `http://${host}:5000`;

  const prevVentLevelRef = useRef("NORMAL");
  const initOnceRef = useRef(false);
  const videoRestartTimerRef = useRef(null);
  const lastRestartAtRef = useRef(0);
  const wasHiddenRef = useRef(false);

  const videoSrc = useMemo(() => {
    if (!videoKey) return "";
    return `${BACKEND_URL}/api/tunnel/video-feed?ts=${videoKey}`;
  }, [videoKey, BACKEND_URL]);

  const speedHintText = useMemo(() => getSpeedHintText(status.avg_speed), [status.avg_speed]);
  const laneReestimateText = useMemo(() => getLaneReestimateText(status), [
    status.lane_reestimate_status,
    status.lane_reestimate_frame_count,
    status.lane_reestimate_window,
  ]);

  const currentVent = useMemo(() => {
    const raw = status.ventilation || {};
    return {
      risk_score_base: Number(raw.risk_score_base ?? 0),
      risk_score_final: clamp01(raw.risk_score_final ?? 0),
      risk_level: raw.risk_level || "NORMAL",
      alarm: Boolean(raw.alarm),
      message: raw.message || getAirMessage(raw.risk_level || "NORMAL"),
      vehicle_count_roi: Number(raw.vehicle_count_roi ?? 0),
      weighted_vehicle_count: Number(raw.weighted_vehicle_count ?? 0),
      traffic_density: Number(raw.traffic_density ?? 0),
      avg_dwell_time_roi: Number(raw.avg_dwell_time_roi ?? 0),
      avg_speed_roi: Number(raw.avg_speed_roi ?? status.avg_speed_roi ?? 0),
    };
  }, [status.ventilation, status.avg_speed_roi]);

  const futureVent = useMemo(() => {
    return buildFutureVentPreview(currentVent, status);
  }, [currentVent, status]);

  const cctvSourceText = useMemo(() => {
    if (cctvSource === "priority") return "목록 구성: 우선 후보 포함";
    if (cctvSource === "its_random") return "목록 구성: ITS 랜덤";
    if (cctvSource === "cache") return "목록 구성: 캐시";
    if (cctvSource === "fallback") return "목록 구성: 테스트 대체";
    return "";
  }, [cctvSource]);

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

  const stopVideo = () => {
    if (videoRestartTimerRef.current) {
      clearTimeout(videoRestartTimerRef.current);
      videoRestartTimerRef.current = null;
    }
    setVideoKey(null);
    setVideoLoading(false);
  };

  const restartVideo = (delay = 900) => {
    const now = Date.now();
    if (now - lastRestartAtRef.current < 1200) return;
    lastRestartAtRef.current = now;

    setVideoLoading(true);

    if (videoRestartTimerRef.current) {
      clearTimeout(videoRestartTimerRef.current);
    }

    setVideoKey(null);

    videoRestartTimerRef.current = setTimeout(() => {
      setVideoKey(Date.now());
    }, delay);
  };

  useEffect(() => {
    let mounted = true;

    const initialize = async () => {
      try {
        if (!initOnceRef.current) {
          const sessionKey = `tunnel_cctv_initialized_${host}`;
          const alreadyInitialized = sessionStorage.getItem(sessionKey) === "1";

          // 백엔드 실제 캐시 상태 확인
          const currentListRes = await fetch(`${BACKEND_URL}/api/tunnel/cctv-list`);
          const currentListData = await currentListRes.json();

          const backendHasList =
            currentListData?.ok &&
            Array.isArray(currentListData?.items) &&
            currentListData.items.length > 0;

          // 세션상 초기화 안 되었거나, 백엔드 캐시가 비어 있으면 다시 초기화
          if (!alreadyInitialized || !backendHasList) {
            const cctvRes = await fetchTunnelCctvUrl(host);

            if (
              !cctvRes?.ok ||
              !Array.isArray(cctvRes?.items) ||
              cctvRes.items.length === 0
            ) {
              throw new Error("CCTV 리스트를 불러오지 못했습니다.");
            }

            if (!mounted) return;
            setCctvSource(cctvRes?.source || "");
            sessionStorage.setItem(sessionKey, "1");
          }

          initOnceRef.current = true;
        }

        const data = await fetchTunnelStatus(BACKEND_URL);
        if (!mounted) return;

        applyStatusData(data);
        restartVideo(900);
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
      stopVideo();
    };
  }, [BACKEND_URL, host]);

  useEffect(() => {
    const currentLevel = currentVent?.risk_level || "NORMAL";
    const prevLevel = prevVentLevelRef.current;

    if (currentLevel === "DANGER" && prevLevel !== "DANGER") {
      alert("🔴 공기질 위험 단계입니다.\n환기 대응 조치가 필요합니다.");
    }

    prevVentLevelRef.current = currentLevel;
  }, [currentVent?.risk_level]);

  /* =========================================================
   * 탭 이동 시: 종료
   * 다시 돌아오면: 새로 시작
   * ========================================================= */
  useEffect(() => {
  const handleVisibilityChange = async () => {
    try {
      if (document.visibilityState === "hidden") {
        wasHiddenRef.current = true;
        setVideoKey(null);
        setVideoLoading(false);
        await stopTunnelStream(BACKEND_URL);
        return;
      }

      if (document.visibilityState === "visible" && wasHiddenRef.current) {
        wasHiddenRef.current = false;
        await restartTunnelStreamRandom(BACKEND_URL);
        await sleep(800);
        restartVideo(600);
      }
    } catch (err) {
      console.error("tab visibility stream control error:", err);
    }
  };

  document.addEventListener("visibilitychange", handleVisibilityChange);

  return () => {
    document.removeEventListener("visibilitychange", handleVisibilityChange);
  };
}, [BACKEND_URL]);

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const handleRandom = async () => {
  try {
    setLoading(true);
    setError("");

    await stopTunnelStream(BACKEND_URL);
    stopVideo();

    await selectRandomCctv(BACKEND_URL);
    await sleep(1200);
    restartVideo(900);
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

      // 현재 스트림만 명시 종료
      await stopTunnelStream(BACKEND_URL);

      // 프론트 img도 끊기
      stopVideo();

      // 같은 CCTV로 다시 video-feed 연결
      await sleep(500);
      restartVideo(700);
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
        headers: { "Content-Type": "application/json" },
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
        headers: { "Content-Type": "application/json" },
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
            <button className="action-btn" onClick={handleRandom} disabled={loading}>
              랜덤선택
            </button>
            <button className="action-btn" onClick={handleRefreshVideo} disabled={loading}>
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
                  <div>영상 연결 중입니다</div>
                  <div className="video-overlay-sub">
                      화면이 계속 나오지 않으면 영상새로고침을 눌러주세요
                  </div>
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
            {cctvSourceText && <div className="video-debug-source">{cctvSourceText}</div>}
          </div>

          <div className="panel panel-status">
            <div className="section-title">🚦 교통흐름 상태</div>

            <div className={`state-badge ${stateClass}`}>{status.state}</div>

            <div className="status-speed-line">
              <span className="status-speed-main">
                평균속도 : {status.avg_speed.toFixed(2)} px/s
              </span>
              <span className="status-speed-sub">({speedHintText})</span>
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
                <button className="summary-mini-btn secondary" onClick={handleLaneSave}>
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
          <div className="panel-air-title">🌫️ 터널 공기질</div>
          <div className="panel-air-grid">
            <AirPanel
              title="현재 터널 공기질"
              subtitle="(기준 : ROI 기반)"
              ventData={currentVent}
            />

            <AirPanel
              title="5분 후 터널 공기질 추정"
              subtitle="(기준 : 현재 상태로 지속 유지 시)"
              ventData={futureVent}
              showForecastBadge
            />
          </div>
        </section>
      </main>
    </div>
  );
}

export default TunnelModule;