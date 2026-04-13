// src/modules/tunnel/compinents/VideoPenel.jsx
// 역할: 터널 탭 내 CCTV 영상 패널 (단일 컴포넌트로 분리)

export default function VideoPanel({ host }) {
  return (
    <div>
      <h3>📺 CCTV</h3>
      <img
        src={`http://${host || window.location.hostname}:5000/api/tunnel/video_feed`}
        style={{ width: "100%", borderRadius: 10 }}
      />
    </div>
  );
}