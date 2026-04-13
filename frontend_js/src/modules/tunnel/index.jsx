/* eslint-disable */
// src/modules/tunnel/index.jsx
// 역할: 터널 탭 UI + 상태 모니터링 + 이벤트 로그
// 탭 라우팅/사이드바는 dashboard/index.jsx가 담당

/* eslint-disable */
// src/modules/tunnel/index.jsx

import { useEffect, useState } from "react";
import axios from "axios";

import VideoPanel from "./components/VideoPanel";
import StatusPanel from "./components/StatusPanel";
import EventLog from "./components/EventLog";
import SpeedChart from "./components/SpeedChart";
import DwellChart from "./components/DwellChart";

export default function TunnelModule({ host }) {
  const BASE = `http://${host || window.location.hostname}:5000/api/tunnel`;

  const [data, setData] = useState({
    state: "NORMAL",
    avg_speed: 0,
    vehicles: [],
    dwell_times: {},
    vehicle_count: 0,
    events: []
  });

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${BASE}/status`);
        setData(res.data);
      } catch (e) {
        console.log(e);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ padding: 20, background: "#0f0f1a", minHeight: "100vh", color: "#fff" }}>
      
      <h2>🚇 스마트 터널 시스템</h2>

      {/* 🔥 메인 GRID */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "2fr 1fr",
        gridTemplateRows: "auto 300px",
        gap: 20
      }}>

        {/* 📺 CCTV */}
        <div style={{ gridRow: "1 / 2" }}>
          <VideoPanel host={host} />
        </div>

        {/* 🚦 상태 + 로그 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <StatusPanel state={data.state} avgSpeed={data.avg_speed} />
          <EventLog events={data.events} />
        </div>

        {/* 📊 하단 그래프 */}
        <div style={{ gridColumn: "1 / 3", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <SpeedChart vehicles={data.vehicles} count={data.vehicle_count} />
          <DwellChart dwell={data.dwell_times} />
        </div>

      </div>
    </div>
  );
}