/* eslint-disable */
// src/modules/plate/components/VideoStream.jsx

export default function VideoStream({ started, streamUrl }) {
  return (
    <div style={s.wrap}>
      {started ? (
        <img src={streamUrl} style={s.video} alt="LPR Stream" />
      ) : (
        <div style={s.placeholder}>
          <div style={{ fontSize: '48px', marginBottom: '12px' }}>🎬</div>
          <div style={{ color: '#606080', fontSize: '14px' }}>
            영상을 선택하고 시작 버튼을 눌러주세요
          </div>
        </div>
      )}
    </div>
  );
}

const s = {
  wrap: {
    flex: 1,
    minHeight: 0,
    background: '#000',
    borderRadius: '12px',
    border: '1px solid #1e293b',
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  video: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    display: 'block',
  },
  placeholder: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
  },
};