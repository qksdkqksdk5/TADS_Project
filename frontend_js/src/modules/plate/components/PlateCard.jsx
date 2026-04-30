/* eslint-disable */
// src/modules/plate/components/PlateCard.jsx
// 번호판 카드 — 클릭하면 VerifyModal 열림

export default function PlateCard({ plate, baseUrl, showTime, onClick }) {
  return (
    <div
      style={{
        ...s.card,
        cursor: showTime ? 'pointer' : 'default',
        borderColor: plate.is_correct === true ? '#14532d'
                   : plate.is_correct === false ? '#7f1d1d'
                   : '#2a2a4a',
      }}
      onClick={showTime ? onClick : undefined}
    >
      {/* 번호판 이미지 */}
      {plate.img_url
        ? <img src={`${baseUrl}${plate.img_url}`} style={s.img} alt="번호판" />
        : <div style={s.imgEmpty}>이미지 없음</div>
      }

      {/* 인식 텍스트 */}
      <div style={s.info}>
        <span style={s.id}>ID: {plate.id}</span>

        {plate.char_diff ? (
          // 정답 입력 후 — 글자별 하이라이트
          <div style={{ display: 'flex', gap: '2px', flexWrap: 'wrap' }}>
            {plate.char_diff.map((c, i) => (
              <span key={i} style={{
                padding: '1px 4px', borderRadius: '3px',
                fontSize: '15px', fontWeight: 700,
                background: c.correct ? '#14532d' : '#7f1d1d',
                color: c.correct ? '#4ade80' : '#f87171',
              }}>
                {c.recognized}
              </span>
            ))}
          </div>
        ) : (
          <span style={{
            ...s.text,
            color: plate.is_fixed ? '#00ff00'
                 : plate.text !== '인식 중...' ? '#00d7ff' : '#ffffff'
          }}>
            {plate.text}
          </span>
        )}

        {/* 재인식 결과 */}
        {plate.retried_text && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontSize: '10px', color: '#475569' }}>재인식:</span>
            <span style={{
              fontSize: '13px', fontWeight: 700,
              color: plate.retry_correct === true ? '#4ade80'
                   : plate.retry_correct === false ? '#f87171' : '#00d7ff'
            }}>
              {plate.retried_text}
            </span>
          </div>
        )}

        {/* 하단 상태 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={s.status}>
            {plate.is_fixed ? '✔ 확정'
             : plate.vote_count > 0 ? `${plate.vote_count}표`
             : '인식 중...'}
          </span>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            {plate.is_correct === true  && <span style={{ fontSize: '11px', color: '#4ade80', fontWeight: 700 }}>✔ 정답</span>}
            {plate.is_correct === false && <span style={{ fontSize: '11px', color: '#f87171', fontWeight: 700 }}>✗ 오답</span>}
            {showTime && plate.detected_at && (
              <span style={s.time}>{plate.detected_at}</span>
            )}
          </div>
        </div>

        {/* 클릭 안내 (history 탭) */}
        {showTime && plate.is_correct === null || showTime && plate.is_correct === undefined ? (
          <div style={s.hint}>클릭해서 정답 입력 / 전처리</div>
        ) : null}
      </div>
    </div>
  );
}

const s = {
  card: {
    background: '#0f0f1a',
    borderRadius: '8px',
    padding: '10px',
    marginBottom: '10px',
    border: '1px solid #2a2a4a',
    transition: 'border-color 0.2s',
  },
  img: { width: '100%', height: '100%', objectFit: 'cover', borderRadius: '4px', marginBottom: '6px' },
  imgEmpty: {
    width: '100%', height: '80px', background: '#2a2a4a',
    borderRadius: '4px', marginBottom: '6px',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#606080', fontSize: '12px',
  },
  info: { display: 'flex', flexDirection: 'column', gap: '3px' },
  id: { fontSize: '11px', color: '#606080' },
  text: { fontSize: '18px', fontWeight: 700, letterSpacing: '2px' },
  status: { fontSize: '11px', color: '#a0a0d0' },
  time: { fontSize: '11px', color: '#475569' },
  hint: { fontSize: '10px', color: '#334155', marginTop: '2px' },
};