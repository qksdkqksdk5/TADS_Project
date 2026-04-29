export default function AccidentModal({ accidentModal, loading, onResolveAccident }) {
  if (!accidentModal) return null;

  return (
    <div className="accident-modal-backdrop">
      <div className="accident-modal">
        <div className="accident-modal-title">🚨 사고 이벤트 감지</div>
        <div className="accident-modal-body">
          <div>
            <span>CCTV</span>
            <strong>{accidentModal.cctv_name || "-"}</strong>
          </div>
          <div>
            <span>날짜</span>
            <strong>{accidentModal.event_date || "-"}</strong>
          </div>
          <div>
            <span>시간</span>
            <strong>{accidentModal.event_time || "-"}</strong>
          </div>
          <div>
            <span>안내</span>
            <strong>
              AI가 사고 상황으로 판단했습니다.
              <br />
              현재 상황을 확인해 주세요.
            </strong>
          </div>
        </div>
        <div className="accident-modal-actions">
          <button
            className="accident-action-btn confirm"
            onClick={() => onResolveAccident("confirm")}
            disabled={loading}
          >
            사고 확정
          </button>
          <button
            className="accident-action-btn normal"
            onClick={() => onResolveAccident("normal")}
            disabled={loading}
          >
            이상 없음
          </button>
        </div>
      </div>
    </div>
  );
}
