// ==========================================
// # 파일명: AirQualityPanel.jsx
// # 역할: 현재 터널 공기질과 5분 후 공기질 추정 패널을 담당

// 위험 점수, 차량 수, 평균속도, 교통밀도, 평균체류시간을 카드 형태로 표시
//   
// # ==========================================


const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const clamp01 = (value) => clamp(Number(value || 0), 0, 1);

function getVentRiskInfo(level) {
  switch (level) {
    case "NORMAL":
      return { label: "정상", className: "risk-normal" };
    case "CAUTION":
      return { label: "주의", className: "risk-caution" };
    case "WARNING":
      return { label: "경고", className: "risk-warning" };
    case "DANGER":
      return { label: "위험", className: "risk-danger" };
    default:
      return { label: "정상", className: "risk-normal" };
  }
}

function getGaugeThumbClass(score) {
  const safeScore = clamp01(score);
  if (safeScore >= 0.85) return "thumb-danger";
  if (safeScore >= 0.6) return "thumb-warning";
  if (safeScore >= 0.35) return "thumb-caution";
  return "thumb-normal";
}

function AirQualityGauge({ level, score }) {
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
        <div className={`air-gauge-thumb ${getGaugeThumbClass(score)}`} />
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
          unit=" 대"
        />
        <AirMetricCard
          label="평균속도"
          value={Number(ventData?.avg_speed_roi ?? 0).toFixed(2)}
          unit=" px/s"
        />
        <AirMetricCard
          label="교통밀도"
          value={`${(Number(ventData?.traffic_density ?? 0) * 100).toFixed(0)}`}
          unit=" %"
        />
        <AirMetricCard
          label="평균체류시간"
          value={Number(ventData?.avg_dwell_time_roi ?? 0).toFixed(2)}
          unit=" 초"
        />
      </div>

      <div className="air-message-line modern">
        {ventData?.message || "공기질 상태 정상"}
      </div>
    </div>
  );
}

export default function AirQualityPanel({ currentVent, futureVent }) {
  return (
    <section className="panel panel-air">
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
  );
}
