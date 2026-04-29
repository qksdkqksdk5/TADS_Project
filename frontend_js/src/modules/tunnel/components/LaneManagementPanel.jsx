export default function LaneManagementPanel({
  laneEditMode,
  laneTargetInput,
  laneTargetLoading,
  laneDisplayCount,
  laneCountColor,
  laneHelperText,
  laneReestimateText,
  reestimateLoading,
  onLaneTargetInputChange,
  onLaneTargetApply,
  onLaneEditStart,
  onLaneEditCancel,
  onLaneReestimate,
  onLaneSave,
}) {
  const laneCountClass =
    laneCountColor === "#facc15" ? "lane-count-warning" : "lane-count-normal";

  return (
    <div className="status-subpanel lane-management-card">
      <div className="status-subpanel-title">차선 관리</div>

      <div className="traffic-summary-grid">
        <div className="summary-card">
          <div className="summary-card-label">차선수</div>
          {laneEditMode ? (
            <>
              <div className="summary-card-value small">목표 차선 수</div>
              <input
                type="number"
                min="2"
                max="4"
                value={laneTargetInput}
                onChange={(event) => onLaneTargetInputChange(event.target.value)}
                className="lane-target-input"
              />
              <div className="lane-action-row">
                <button
                  className="summary-mini-btn"
                  onClick={onLaneTargetApply}
                  disabled={laneTargetLoading}
                >
                  {laneTargetLoading ? "적용중..." : "적용"}
                </button>
                <button
                  className="summary-mini-btn secondary"
                  onClick={onLaneEditCancel}
                  disabled={laneTargetLoading}
                >
                  취소
                </button>
              </div>
            </>
          ) : (
            <>
              <div className={`summary-card-value lane-management-status-text ${laneCountClass}`}>
                {laneDisplayCount}차선
              </div>
              {laneHelperText && (
                <div className="summary-card-value small lane-warning-text">
                  {laneHelperText}
                </div>
              )}
              <button className="summary-mini-btn" onClick={onLaneEditStart}>
                수정
              </button>
            </>
          )}
        </div>

        <div className="summary-card">
          <div className="summary-card-label">차선재추정</div>
          <div className="summary-card-value lane-management-status-text">
            {laneReestimateText}
          </div>
          <button
            className="summary-mini-btn"
            onClick={onLaneReestimate}
            disabled={reestimateLoading}
          >
            {reestimateLoading ? "요청중..." : "재추정"}
          </button>
        </div>

        <div className="summary-card">
          <div className="summary-card-label">차선저장</div>
          <div className="summary-card-value lane-management-status-text">
            현재 차선 메모리
          </div>
          <button className="summary-mini-btn secondary" onClick={onLaneSave}>
            저장
          </button>
        </div>
      </div>
    </div>
  );
}
