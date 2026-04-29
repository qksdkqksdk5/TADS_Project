// ==========================================
// # 파일명: StatusPanel.jsx
// # 역할: 교통흐름+사고상태 담당

// NORMAL, CONGESTION, JAM, ACCIDENT 상태를 badge 형태로 보여주고, 
// 평균속도와 속도 해석 문구를 함께 표시합니다.
//   
// # ==========================================

export default function StatusPanel({
  displayState,
  stateClass,
  avgSpeed,
  speedHintText,
}) {
  return (
    <>
      <div className="status-title-row">
        <div className="section-title">🚦 교통흐름 상태</div>
        <div className="traffic-legend">
          <span className="traffic-legend-item normal">정상</span>
          <span className="traffic-legend-item congestion">혼잡</span>
          <span className="traffic-legend-item jam">정체</span>
          <span className="traffic-legend-item accident">사고</span>
        </div>
      </div>

      <div className="status-subpanel traffic-state-card">
        <div className={`state-badge ${stateClass}`}>{displayState}</div>

        <div className="status-speed-line">
          <span className="status-speed-main">
            평균속도 : {Number(avgSpeed || 0).toFixed(2)} px/s
          </span>
          <span className="status-speed-sub">({speedHintText})</span>
        </div>
      </div>
    </>
  );
}
