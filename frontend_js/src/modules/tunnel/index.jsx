// ==========================================
// # 파일명: index.jsx
// # 역할: 터널 화면의 메인 컨테이너
// 
// # - BACKEND_URL 생성
// # - status 상태 관리
// # - 1초 단위 상태 polling
// # - CCTV 영상 URL restart 처리
// # - 랜덤 CCTV 선택
// # - 차선 재추정/저장/목표 차선 수 설정
// # - 사고 이벤트 모달 처리
// # - 공기질 current/future 데이터 계산

// #
// # 참고:
// # - 실시간 CCTV는 외부 스트림이라 끊길 수 있기 때문에, 
//     index.jsx에서 videoFeedUrl에 timestamp를 붙여 재연결하고, 
//     영상 새로고침이나 탭 이탈 상황도 처리
// # ==========================================



import React, { useEffect, useMemo, useRef, useState } from "react";
import "./index.css";
import {
  fetchTunnelCctvList,
  fetchTunnelStatus,
  fetchTunnelCctvUrl,
  fetchTunnelEventStats,
  requestLaneReestimate,
  resolveTunnelAccidentEvent,
  saveTunnelLaneMemory,
  selectRandomCctv,
  setTunnelTargetLaneCount,
  stopTunnelStream,
} from "./api";
import AccidentModal from "./components/AccidentModal";
import AirQualityPanel from "./components/AirQualityPanel";
import EventPanel from "./components/EventPanel";
import LaneManagementPanel from "./components/LaneManagementPanel";
import StatusPanel from "./components/StatusPanel";
import VideoPanel from "./components/VideoPanel";

/* =========================================================
 * 공통 유틸
 * ========================================================= */
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const clamp01 = (value) => clamp(Number(value || 0), 0, 1);

function getSpeedHintText(avgSpeed) {
  const speed = Number(avgSpeed || 0);

  if (speed <= 1.8) return "실제속도 30km/h 이하 추정";
  if (speed <= 3.0) return "실제속도 30~50km/h 추정";
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
  if (state === "SUSPECT") return "suspect";
  if (state === "CONFIRMED") return "accident";
  if (state === "ERROR") return "error";
  return "ready";
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

function TunnelModule({ host }) {
  const [status, setStatus] = useState({
    state: "READY",
    traffic_state: "NORMAL",
    accident_status: "NONE",
    pending_accident_event: null,
    avg_speed: 0,
    avg_speed_roi: 0,
    vehicle_count: 0,
    accident: false,
    lane_count: 0,
    target_lane_count: null,
    lane_count_stable: false,
    template_confirmed: false,
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
  const [videoFeedUrl, setVideoFeedUrl] = useState("");
  const [videoLoading, setVideoLoading] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reestimateLoading, setReestimateLoading] = useState(false);
  const [laneEditMode, setLaneEditMode] = useState(false);
  const [laneTargetInput, setLaneTargetInput] = useState("");
  const [laneTargetLoading, setLaneTargetLoading] = useState(false);
  const [accidentModal, setAccidentModal] = useState(null);
  const [resolvedAccidentIds, setResolvedAccidentIds] = useState(() => new Set());
  const [eventTab, setEventTab] = useState("logs");
  const [eventStats, setEventStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [lastSelectedCctv, setLastSelectedCctv] = useState(() => {
    try {
      const saved = sessionStorage.getItem(`tunnel_last_cctv_${host}`);
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const BACKEND_URL = `http://${host}:5000`;

  const prevVentLevelRef = useRef("NORMAL");
  const initOnceRef = useRef(false);
  const videoRestartTimerRef = useRef(null);
  const videoErrorTimerRef = useRef(null);
  const lastRestartAtRef = useRef(0);
  const wasHiddenRef = useRef(false);
  const stoppedOnExitRef = useRef(false);

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

  const rememberCctv = (data) => {
    const name = data?.cctv_name;
    const url = data?.cctv_url;

    if (!name || name === "-") return;

    const next = { name, url: url || "" };
    setLastSelectedCctv(next);

    try {
      sessionStorage.setItem(`tunnel_last_cctv_${host}`, JSON.stringify(next));
    } catch {
      // sessionStorage를 사용할 수 없는 환경에서는 메모리 상태만 유지한다.
    }
  };

  const stopBackendStream = async () => {
    try {
      await stopTunnelStream(BACKEND_URL);
    } catch (err) {
      console.error("stop tunnel stream error:", err);
    }
  };

  const applyStatusData = (data) => {
    rememberCctv(data);

    setStatus({
      state: data?.state ?? "READY",
      traffic_state: data?.traffic_state ?? data?.state ?? "NORMAL",
      accident_status: data?.accident_status ?? "NONE",
      pending_accident_event: data?.pending_accident_event ?? null,
      avg_speed: Number(data?.avg_speed ?? 0),
      avg_speed_roi: Number(data?.avg_speed_roi ?? 0),
      vehicle_count: Number(data?.vehicle_count ?? 0),
      accident: Boolean(data?.accident ?? false),
      lane_count: Number(data?.lane_count ?? 0),
      target_lane_count:
        data?.target_lane_count === null || data?.target_lane_count === undefined
          ? null
          : Number(data.target_lane_count),
      lane_count_stable: Boolean(data?.lane_count_stable ?? false),
      template_confirmed: Boolean(data?.template_confirmed ?? false),
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
    if (videoErrorTimerRef.current) {
      clearTimeout(videoErrorTimerRef.current);
      videoErrorTimerRef.current = null;
    }
    setVideoFeedUrl("");
    setVideoLoading(false);
  };

  const restartVideo = (delay = 900, force = false) => {
    const now = Date.now();
    if (!force && now - lastRestartAtRef.current < 1200) return;
    lastRestartAtRef.current = now;

    setVideoLoading(true);

    if (videoRestartTimerRef.current) {
      clearTimeout(videoRestartTimerRef.current);
    }

    setVideoFeedUrl("");

    videoRestartTimerRef.current = setTimeout(() => {
      stoppedOnExitRef.current = false;
      setVideoFeedUrl(`${BACKEND_URL}/api/tunnel/video-feed?t=${Date.now()}`);
    }, delay);
  };

  const retryVideoAfterError = () => {
    if (videoErrorTimerRef.current) return;

    videoErrorTimerRef.current = setTimeout(() => {
      videoErrorTimerRef.current = null;
      restartVideo(0);
    }, 1800);
  };

  useEffect(() => {
    let mounted = true;

    const initialize = async () => {
      try {
        if (!initOnceRef.current) {
          const sessionKey = `tunnel_cctv_initialized_${host}`;
          const alreadyInitialized = sessionStorage.getItem(sessionKey) === "1";

          // 백엔드 실제 캐시 상태 확인
          const currentListData = await fetchTunnelCctvList(BACKEND_URL);

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
      stoppedOnExitRef.current = true;
      stopBackendStream();
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

  useEffect(() => {
    const event = status.pending_accident_event;
    if (!event?.event_id) return;
    if (resolvedAccidentIds.has(event.event_id)) return;
    if (accidentModal?.event_id === event.event_id) return;

    setAccidentModal(event);
  }, [status.pending_accident_event, resolvedAccidentIds, accidentModal?.event_id]);

  const loadEventStats = async () => {
    try {
      setStatsLoading(true);
      const data = await fetchTunnelEventStats(BACKEND_URL);
      setEventStats(data);
    } catch (err) {
      console.error("event stats fetch error:", err);
    } finally {
      setStatsLoading(false);
    }
  };

  useEffect(() => {
    if (eventTab === "stats") {
      loadEventStats();
    }
  }, [eventTab, BACKEND_URL]);

  /* =========================================================
   * 탭 이동 시: 종료
   * 다시 돌아오면: 새로 시작
   * ========================================================= */
  useEffect(() => {
  const handleVisibilityChange = async () => {
    try {
      if (document.visibilityState === "hidden") {
        wasHiddenRef.current = true;
        stopVideo();
        if (!stoppedOnExitRef.current) {
          stoppedOnExitRef.current = true;
          await stopBackendStream();
        }
        return;
      }

      if (document.visibilityState === "visible" && wasHiddenRef.current) {
        wasHiddenRef.current = false;
        // 마지막 CCTV는 백엔드 service.current_cctv가 보존하므로
        // select-random 없이 video-feed만 새 timestamp로 재연결한다.
        restartVideo(300, true);
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
    restartVideo(900, true);
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

      // 현재 CCTV는 유지하고 img 연결만 끊은 뒤 새 timestamp로 재연결
      stopVideo();
      restartVideo(300, true);
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

      const data = await requestLaneReestimate(BACKEND_URL);

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

      const data = await saveTunnelLaneMemory(BACKEND_URL);

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

  const handleLaneTargetApply = async () => {
    const nextLaneCount = Number(laneTargetInput);

    if (![2, 3, 4].includes(nextLaneCount)) {
      setError("목표 차선 수는 2, 3, 4만 입력할 수 있습니다.");
      return;
    }

    try {
      setLaneTargetLoading(true);
      setError("");

      const data = await setTunnelTargetLaneCount(BACKEND_URL, nextLaneCount);

      if (!data?.ok) {
        setError(data?.message || "목표 차선 수 설정 실패");
        return;
      }

      setLaneEditMode(false);
      const refreshed = await fetchTunnelStatus(BACKEND_URL);
      applyStatusData(refreshed);
    } catch (err) {
      console.error("lane target count error:", err);
      setError("목표 차선 수 설정 실패");
    } finally {
      setLaneTargetLoading(false);
    }
  };

  const handleResolveAccident = async (action) => {
    if (!accidentModal?.event_id) return;

    try {
      setLoading(true);
      const data = await resolveTunnelAccidentEvent(
        BACKEND_URL,
        accidentModal.event_id,
        action
      );

      if (!data?.ok) {
        setError(data?.message || "사고 이벤트 처리 실패");
        return;
      }

      setResolvedAccidentIds((prev) => {
        const next = new Set(prev);
        next.add(accidentModal.event_id);
        return next;
      });
      setAccidentModal(null);

      const refreshed = await fetchTunnelStatus(BACKEND_URL);
      applyStatusData(refreshed);

      if (eventTab === "stats") {
        loadEventStats();
      }
    } catch (err) {
      console.error("resolve accident error:", err);
      setError("사고 이벤트 처리 실패");
    } finally {
      setLoading(false);
    }
  };

  const displayState = useMemo(() => {
    if (status.accident_status === "CONFIRMED") return "🔴 사고 확정";
    if (status.accident_status === "SUSPECT") return "🚨 사고 의심";
    return status.traffic_state || status.state;
  }, [status.accident_status, status.traffic_state, status.state]);

  const stateClass = getStateClass(
    status.accident_status === "CONFIRMED"
      ? "CONFIRMED"
      : status.accident_status === "SUSPECT"
      ? "SUSPECT"
      : status.traffic_state || status.state
  );

  const laneDisplayCount = status.target_lane_count || status.lane_count;
  const hasTargetLaneCount = status.target_lane_count !== null && status.target_lane_count !== undefined;
  const laneTargetPending =
    hasTargetLaneCount &&
    (!status.template_confirmed || Number(status.lane_count) !== Number(status.target_lane_count));
  const laneCountColor = laneTargetPending ? "#facc15" : "#ffffff";
  const laneHelperText = laneTargetPending
    ? status.lane_reestimate_status === "reestimating"
      ? "차선 안정화 중"
      : "재추정 대기중"
    : "";

  return (
    <div className="smart-page">
      <main className="smart-main">
        <section className="panel panel-header">
          <div className="panel-header-left">
            <div className="panel-title">🚨 스마트 터널 시스템</div>
            <div className="panel-subtitle">{status.cctv_name || lastSelectedCctv?.name || "-"}</div>
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
          <VideoPanel
            videoLoading={videoLoading}
            videoFeedUrl={videoFeedUrl}
            status={status}
            lastSelectedCctv={lastSelectedCctv}
            cctvSourceText={cctvSourceText}
            onVideoLoad={() => {
              setVideoLoading(false);
              setError("");
            }}
            onVideoError={() => {
              setVideoLoading(false);
              setError("영상 스트리밍 연결 실패");
              retryVideoAfterError();
            }}
          />

          <div className="panel panel-status">
            <StatusPanel
              displayState={displayState}
              stateClass={stateClass}
              avgSpeed={status.avg_speed}
              speedHintText={speedHintText}
            />

            <LaneManagementPanel
              laneEditMode={laneEditMode}
              laneTargetInput={laneTargetInput}
              laneTargetLoading={laneTargetLoading}
              laneDisplayCount={laneDisplayCount}
              laneCountColor={laneCountColor}
              laneHelperText={laneHelperText}
              laneReestimateText={laneReestimateText}
              reestimateLoading={reestimateLoading}
              onLaneTargetInputChange={setLaneTargetInput}
              onLaneTargetApply={handleLaneTargetApply}
              onLaneEditStart={() => {
                setLaneTargetInput(String(status.target_lane_count || status.lane_count || 2));
                setLaneEditMode(true);
              }}
              onLaneEditCancel={() => {
                setLaneEditMode(false);
                setLaneTargetInput("");
              }}
              onLaneReestimate={handleLaneReestimate}
              onLaneSave={handleLaneSave}
            />

            <EventPanel
              eventTab={eventTab}
              setEventTab={setEventTab}
              status={status}
              eventStats={eventStats}
              statsLoading={statsLoading}
            />
          </div>
        </section>

        <AirQualityPanel currentVent={currentVent} futureVent={futureVent} />
      </main>

      <AccidentModal
        accidentModal={accidentModal}
        loading={loading}
        onResolveAccident={handleResolveAccident}
      />
    </div>
  );
}

export default TunnelModule;
