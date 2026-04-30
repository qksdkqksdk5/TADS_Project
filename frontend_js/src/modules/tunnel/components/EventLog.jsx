// src/modules/tunnel/components/EventLog.jsx
// 역할: 터널 탭 내 이벤트 로그 패널

export default function EventLog({ status }) {
  const eventLogs = Array.isArray(status?.event_logs) ? status.event_logs : [];
  const events = Array.isArray(status?.events) ? status.events : [];

  if (eventLogs.length > 0) {
    return eventLogs
      .slice()
      .reverse()
      .map((event, idx) => (
        <div key={`${event}-${idx}`} className="event-item">
          {event}
        </div>
      ));
  }

  if (events.length > 0) {
    return events.map((event, idx) => (
      <div key={`${event}-${idx}`} className="event-item">
        {event}
      </div>
    ));
  }

  return <div className="event-empty">이상 징후 없음 (정상 흐름 유지)</div>;
}
