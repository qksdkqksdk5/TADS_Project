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
    events: [],
    accident: false,
    accident_label: "NONE",
    lane_count_estimated: 0,
    frame_id: 0,
    source_name: "idle"
  });

  // 탭 진입/이탈 시 service 제어
  useEffect(() => {
    const startService = async () => {
      try {
        await axios.post(`${BASE}/start`);
      } catch (e) {
        console.log("start 실패", e);
      }
    };

    const stopService = async () => {
      try {
        await axios.post(`${BASE}/stop`);
      } catch (e) {
        console.log("stop 실패", e);
      }
    };

    startService();

    return () => {
      stopService();
    };
  }, [BASE]);

  // 상태 polling
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await axios.get(`${BASE}/status`);
        setData(res.data);
      } catch (e) {
        console.log("status 실패", e);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);

    return () => clearInterval(interval);
  }, [BASE]);

  const isRunning = data.source_name === "running" || data.source_name === "test_accident.mp4";

  return (
    <div style={{ padding: 20, background: "#0f0f1a", minHeight: "100vh", color: "#fff" }}>
      <h2>🚇 스마트 터널 시스템</h2>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gridTemplateRows: "auto 300px",
          gap: 20
        }}
      >
        <div style={{ gridRow: "1 / 2" }}>
          <VideoPanel host={host} active={isRunning} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <StatusPanel state={data.state} avgSpeed={data.avg_speed} />
          <EventLog events={data.events} />
        </div>

        <div
          style={{
            gridColumn: "1 / 3",
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 20
          }}
        >
          <SpeedChart vehicles={data.vehicles} count={data.vehicle_count} />
          <DwellChart dwell={data.dwell_times} />
        </div>
      </div>
    </div>
  );
}