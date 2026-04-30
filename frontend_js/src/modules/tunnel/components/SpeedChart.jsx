// src/modules/tunnel/components/SpeedChart.jsx
// 역할: 터널 탭 내 차량 속도 차트 패널 (단일 컴포넌트로 분리)

import { BarChart, Bar, XAxis, YAxis, Tooltip } from "recharts";

export default function SpeedChart({ vehicles, count }) {
  const data = vehicles.slice(0, 10).map(v => ({
    name: `ID${v.id}`,
    speed: v.speed
  }));

  return (
    <div className="chart-panel">
      <h3>📊 차량 속도 (ROI)</h3>
      <div>총 차량 수: {count}</div>

      {data.length > 0 ? (
        <BarChart width={400} height={200} data={data}>
          <XAxis dataKey="name" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="speed" />
        </BarChart>
      ) : (
        <div className="chart-empty-text">표시할 차량 속도 데이터가 없습니다.</div>
      )}
    </div>
  );
}
