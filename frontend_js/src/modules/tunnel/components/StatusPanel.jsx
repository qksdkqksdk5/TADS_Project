// src/modules/tunnel/compinents/StatusPanel.jsx
// 역할: 터널 탭 내 상태 표시 패널 (단일 컴포넌트로 분리)

export default function StatusPanel({ state, avgSpeed }) {

  const getColor = () => {
    if (state === "ACCIDENT") return "red";
    if (state === "JAM") return "orange";
    if (state === "CONGESTION") return "yellow";
    return "lightgreen";
  };

  return (
    <div style={{ background: "#1a1a2e", padding: 20, borderRadius: 10 }}>

      <h3>🚦 상태</h3>
      <div style={{ color: getColor(), fontSize: 24 }}>
        ● {state}
      </div>

      <h3 style={{ marginTop: 20 }}>⚡ 평균 속도</h3>
      <div>{avgSpeed} px/s</div>

      <div style={{
        marginTop: 10,
        padding: 10,
        background: "#111",
        fontSize: 12
      }}>
        <b>기준</b><br />
        km/h: &lt;30 정체 / 30~50 혼잡 / 50↑ 정상<br />
        px/s: &lt;3 정체 / 4~10 혼잡 / 10↑ 정상
      </div>

    </div>
  );
}