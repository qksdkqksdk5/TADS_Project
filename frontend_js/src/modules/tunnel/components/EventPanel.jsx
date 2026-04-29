import EventLog from "./EventLog";

export default function EventPanel({
  eventTab,
  setEventTab,
  status,
  eventStats,
  statsLoading,
}) {
  return (
    <div className="status-subpanel event-log-card">
      <div className="event-card-tabs">
        <button
          className={`event-tab-btn ${eventTab === "logs" ? "active" : ""}`}
          onClick={() => setEventTab("logs")}
        >
          이벤트 로그
        </button>
        <button
          className={`event-tab-btn ${eventTab === "stats" ? "active" : ""}`}
          onClick={() => setEventTab("stats")}
        >
          이벤트 통계관리
        </button>
      </div>

      {eventTab === "logs" ? (
        <div className="event-log scrollable-log">
          <EventLog status={status} />
        </div>
      ) : (
        <div className="event-stats-panel scrollable-log">
          {statsLoading ? (
            <div className="event-empty">통계 불러오는 중...</div>
          ) : (
            <>
              <div className="stats-date-line">기준일: {eventStats?.date || "-"}</div>
              <div className="stats-grid">
                <div className="stats-row">
                  <span>사고 의심</span>
                  <strong>{eventStats?.total_suspect ?? 0}건</strong>
                </div>
                <div className="stats-row">
                  <span>사고 확정</span>
                  <strong>{eventStats?.confirmed ?? 0}건</strong>
                </div>
                <div className="stats-row">
                  <span>이상 없음</span>
                  <strong>{eventStats?.false_alarm ?? 0}건</strong>
                </div>
                <div className="stats-row">
                  <span>확정률</span>
                  <strong>{eventStats?.confirm_rate ?? 0}%</strong>
                </div>
                <div className="stats-row">
                  <span>오탐률</span>
                  <strong>{eventStats?.false_alarm_rate ?? 0}%</strong>
                </div>
              </div>

              <div className="recent-title">최근 처리 기록</div>
              <div className="recent-events-list">
                {(eventStats?.recent_events || []).length > 0 ? (
                  eventStats.recent_events.map((event) => (
                    <div
                      key={event.event_id || `${event.event_datetime}-${event.cctv_name}`}
                      className="recent-event-item"
                    >
                      <span>{event.event_time}</span>
                      <strong>{event.operator_action || event.event_status}</strong>
                      <em>{event.cctv_name || "-"}</em>
                    </div>
                  ))
                ) : (
                  <div className="event-empty compact">최근 처리 기록 없음</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
