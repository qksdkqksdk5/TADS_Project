/* eslint-disable 브랜치 테스트2*/
import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

export default function RaspiModule({ host }) {
  const clientId = useRef(Math.random().toString(36).substring(7)).current;

  // 좌표 및 상태 관리
  const [panPos, setPanPos] = useState(0);
  const [tiltPos, setTiltPos] = useState(0);
  const [lastCmd, setLastCmd] = useState("READY");
  
  // 축별 스텝 및 속도 설정
  const [stepX, setStepX] = useState(1); 
  const [stepZ, setStepZ] = useState(1); // UI 표기용 (1, 5, 10)
  const [speedX, setStepSpeedX] = useState(100); 
  const [speedZ, setStepSpeedZ] = useState(10); 

  // Y축 가동 범위 제한 (물리적 안전장치)
  const TILT_LIMIT_MIN = -1.8;
  const TILT_LIMIT_MAX = 1.1;

  const [isConnecting, setIsConnecting] = useState(true);
  const [isDetecting, setIsDetecting] = useState(false);
  const [isAutoTracking, setIsAutoTracking] = useState(false);
  const [isPatrolling, setIsPatrolling] = useState(false);
  const [fireAlert, setFireAlert] = useState(false);
  const [streamKey, setStreamKey] = useState(Date.now());
  const [isCombinedMode, setIsCombinedMode] = useState(false);
  const [motorEnabled, setMotorEnabled] = useState(false);
  const [maxTemp, setMaxTemp] = useState(0);

  const BACKEND_HOST = host || window.location.hostname;
  const BASE_URL = `${window.location.protocol}//${BACKEND_HOST}/api/raspi`;

  useEffect(() => {
    console.log("🌐 [TADS] Backend Target URL:", BASE_URL);
  }, [BASE_URL]);

  const [videoUrls, setVideoUrls] = useState({
    normal: `${BASE_URL}/video_feed?type=normal&t=${Date.now()}`,
    thermal: `${BASE_URL}/video_feed?type=thermal&t=${Date.now()}`
  });

  const client = useRef(axios.create({
    baseURL: BASE_URL,
    headers: { 'ngrok-skip-browser-warning': 'true' }
  })).current;

  const errorCount = useRef(0);
  const initialized = useRef(false);

  const handleStreamError = useCallback(() => {
    if (errorCount.current > 15) return;
    errorCount.current += 1;
    setTimeout(() => {
      const now = Date.now();
      setVideoUrls({
        normal: `${BASE_URL}/video_feed?type=normal&t=${now}`,
        thermal: `${BASE_URL}/video_feed?type=thermal&t=${now}`
      });
      setStreamKey(now);
    }, 2000);
  }, [BASE_URL]);

  const fetchStatus = useCallback(async (gcode = null, mode = null) => {
    try {
      let url = `/control?client_id=${clientId}&`;
      if (gcode) url += `cmd=${encodeURIComponent(gcode)}&`;
      if (mode) url += `mode=${mode}&`;

      // 타임아웃을 10초로 대폭 연장하여 안정성 확보
      const response = await client.get(url, { timeout: 10000 });
      if (response.data) {
        if (gcode) setLastCmd(gcode);
        if (gcode === "M17") setMotorEnabled(true);
        if (gcode === "M18") setMotorEnabled(false);
        
        // 화재 감지 및 기타 상태 업데이트
        if (response.data.fire !== undefined) {
          setFireAlert(response.data.fire);
        }
        if (response.data.auto !== undefined) {
          setIsAutoTracking(response.data.auto);
        }
        if (response.data.patrol !== undefined) {
          setIsPatrolling(response.data.patrol);
        }
        if (response.data.detect !== undefined) {
          setIsDetecting(response.data.detect);
        }
        if (response.data.max_temp !== undefined) {
          setMaxTemp(response.data.max_temp);
        }
        if (response.data.x !== undefined) {
          setPanPos(response.data.x);
        }
        if (response.data.y !== undefined) {
          setTiltPos(response.data.y);
        }
      }
      setIsConnecting(false);
      return response.data; 
    } catch (err) {
      if (err.response && err.response.status === 403) {
        alert(err.response.data.message);
      } else {
        setIsConnecting(true);
      }
      throw err;
    }
  }, [client, clientId]);

  const [isInitializing, setIsInitializing] = useState(false);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    const startSystem = async () => {
      setIsInitializing(true);
      try {
        // 1. 현재 상태 먼저 확인
        const currentStatus = await fetchStatus();
        
        // 2. 이미 시스템이 시작되어 있다면 불필요한 리셋 건너뜀
        if (currentStatus && currentStatus.status === "ok" && (currentStatus.patrol || currentStatus.auto)) {
          console.log("✅ System already running, skipping full initialization");
        } else {
          // 신규 시작인 경우에만 초기화 진행
          await client.post(`/start`);
          await new Promise(r => setTimeout(r, 1000));
          await fetchStatus("M17");
          await new Promise(r => setTimeout(r, 500));
          await fetchStatus("G92 X0 Y0 Z0"); 
          await new Promise(r => setTimeout(r, 500));
          await fetchStatus("M211 S0"); 
          await new Promise(r => setTimeout(r, 500));
          await fetchStatus("G91"); // 상대 좌표 모드 유지
        }
      } catch (err) { 
        console.error("❌ Initialization failed", err); 
      } finally {
        setIsInitializing(false);
      }
    };

    startSystem();
    const timer = setInterval(() => fetchStatus(), 2000);
    return () => clearInterval(timer);
  }, [client, fetchStatus]);

  const move = (x = 0, y = 0) => {
    if (isAutoTracking) {
      if (!window.confirm("자동 추적 중입니다. 수동 제어를 위해 추적을 끌까요?")) return;
      toggleTracking();
      return;
    }

    const actualY = y * 0.1;
    const newTilt = parseFloat((tiltPos + actualY).toFixed(2));
    
    if (y !== 0 && (newTilt < TILT_LIMIT_MIN || newTilt > TILT_LIMIT_MAX)) {
      setLastCmd("LIMIT REACHED");
      return;
    }

    const invertedX = x !== 0 ? -x : 0;
    let gcode = "G1 ";
    if (x !== 0) gcode += `X${invertedX} F${speedX} `;
    if (y !== 0) gcode += `Y${actualY} F${speedZ} `;

    fetchStatus(gcode.trim());
    setPanPos(p => parseFloat((p + invertedX).toFixed(2)));
    setTiltPos(newTilt);
  };

  const stopEmergency = () => {
    setLastCmd("STOPPED");
    return fetchStatus("M410"); 
  };

  // 💡 [수정] 현재 좌표값의 정반대 명령을 직접 내려서 0,0으로 복귀
  const goHome = async () => {
    try {
      // 1. 기존 동작 정지 및 모터 재활성화 (M410 후에는 종종 M17 필요)
      setLastCmd("HOMING STARTED...");
      await fetchStatus("M410"); 
      await new Promise(r => setTimeout(r, 300)); 
      await fetchStatus("M17");
      await new Promise(r => setTimeout(r, 200));

      // 2. 복귀 좌표 계산
      const reverseX = -panPos;
      const reverseY = -tiltPos;

      if (Math.abs(reverseX) < 0.01 && Math.abs(reverseY) < 0.01) {
        setLastCmd("ALREADY AT HOME");
        setPanPos(0);
        setTiltPos(0);
        return;
      }

      // 3. 복귀 명령 생성 (G91 상대 좌표 모드 활용)
      let gcode = "G1 ";
      if (Math.abs(reverseX) > 0) gcode += `X${reverseX.toFixed(2)} `;
      if (Math.abs(reverseY) > 0) gcode += `Y${reverseY.toFixed(2)} `;
      gcode += "F100"; // 복귀는 조금 더 빠르게
      
      await fetchStatus(gcode.trim());

      // 4. 성공 시 상태 동기화
      setPanPos(0);
      setTiltPos(0);
      setLastCmd(`HOMING DONE: ${gcode.trim()}`);
    } catch (err) {
      console.error("Homing failed", err);
      setLastCmd("HOMING ERROR");
    }
  };

  const resetCoordinates = async () => {
    try {
      await stopEmergency();
      await new Promise(r => setTimeout(r, 300));
      await fetchStatus("M17"); // 정지 후 모터 재활성화
      await new Promise(r => setTimeout(r, 200));
      await fetchStatus("G92 X0 Y0 Z0"); 
      setPanPos(0);
      setTiltPos(0);
      setLastCmd("COORDINATES RESET");
    } catch (err) {
      setLastCmd("RESET FAILED");
    }
  };

  const toggleDetection = () => fetchStatus(null, isDetecting ? "detect_off" : "detect_on");
  
  const toggleTracking = async () => {
    const nextState = !isAutoTracking;
    setIsAutoTracking(nextState); // 즉시 상태 변경 (피드백 강화)
    try {
      await fetchStatus(null, nextState ? "auto_on" : "auto_off");
    } catch (err) {
      setIsAutoTracking(!nextState); // 실패 시 복구
    }
  };

  const togglePatrol = async () => {
    const nextState = !isPatrolling;
    setIsPatrolling(nextState);
    try {
      await fetchStatus(null, nextState ? "patrol_on" : "patrol_off");
    } catch (err) {
      setIsPatrolling(!nextState);
    }
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100vh', padding: '20px 40px', boxSizing: 'border-box',
      fontFamily: 'Inter, sans-serif', transition: '0.5s', overflow: 'hidden',
      background: fireAlert ? '#4a0000' : '#0a0a12', color: '#e0e0ff'
    }}>
      <header style={{ marginBottom: '20px', textAlign: 'center', flexShrink: 0 }}>
        <h1 style={{ fontSize: '32px', fontWeight: 800, letterSpacing: '-1px', margin: 0 }}>AI DUAL-VISION MONITORING</h1>
      </header>

      <div style={{ display: 'flex', gap: '0px', justifyContent: 'center', alignItems: 'center', flex: 1, minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '50px', flex: 1, height: '100%' }}>
          <div style={{ display: 'flex', gap: '20px', height: '70%', width: '100%', justifyContent: 'center', alignItems: 'center' }}>
            <div style={videoWrapperStyle}><img key={`normal-${streamKey}`} src={videoUrls.normal} style={videoImgStyle} alt="Normal" /></div>
            <div style={videoWrapperStyle}><img key={`thermal-${streamKey}`} src={videoUrls.thermal} style={{ ...videoImgStyle, transform: 'rotate(90deg) scaleX(-1)' }} alt="Thermal" /></div>
          </div>
          <div style={coordBoxStyle}>
            <span style={{ fontSize: '12px', color: '#818cf8', fontWeight: 800 }}>SYSTEM STATUS</span>
            <div style={{ fontSize: '20px', fontFamily: 'monospace', fontWeight: 600, display: 'flex', gap: '20px', justifyContent: 'center' }}>
              <span>X: {panPos.toFixed(2)} | Y: {tiltPos.toFixed(2)}</span>
              <span style={{ color: maxTemp > 40 ? '#ef4444' : '#10b981' }}>
                🌡️ {maxTemp.toFixed(1)}°C
              </span>
            </div>
            
            {/* 온도 가이드 추가 */}
            <div style={{ 
              marginTop: '15px', padding: '10px', background: 'rgba(0,0,0,0.3)', borderRadius: '8px',
              fontSize: '11px', display: 'flex', flexDirection: 'column', gap: '5px', textAlign: 'left'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }}></div>
                <span>정상 (0~40°C): 안전한 상태입니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#f59e0b' }}></div>
                <span>주의 (40~60°C): 이상 고온이 감지되었습니다. 주의가 필요합니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#ef4444' }}></div>
                <span>위험 (60°C 이상): 화재 발생 가능성이 매우 높습니다! 즉시 확인하십시오.</span>
              </div>
            </div>
          </div>
        </div>

        <div style={controlPanelStyle}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '20px' }}>
            <button onClick={togglePatrol} style={{ ...actionBtnStyle, background: isPatrolling ? '#f59e0b' : '#374151' }}>
              {isPatrolling ? "🛡️ 감시모드: ACTIVE" : "🛡️감시모드: OFF"}
            </button>
            <button onClick={stopEmergency} style={{ ...actionBtnStyle, background: '#ef4444' }}>🚨 EMERGENCY STOP</button>
            <button onClick={resetCoordinates} style={{ ...actionBtnStyle, background: '#6366f1', fontSize: '13px' }}>📍 SET CURRENT AS 0,0 (RESET)</button>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 75px)', gap: '15px', justifyContent: 'center' }}>
              <Btn text="↖" onClick={() => move(-stepX, stepZ)} />
              <Btn text="▲" onClick={() => move(0, stepZ)} active />
              <Btn text="↗" onClick={() => move(stepX, stepZ)} />
              <Btn text="◀" onClick={() => move(-stepX, 0)} active />
              <Btn text="🏠" bg="#f59e0b" onClick={goHome} />
              <Btn text="▶" onClick={() => move(stepX, 0)} active />
              <Btn text="↙" onClick={() => move(-stepX, -stepZ)} />
              <Btn text="▼" onClick={() => move(0, -stepZ)} active />
              <Btn text="↘" onClick={() => move(stepX, -stepZ)} />
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '15px' }}>
             <div style={stepBoxStyle}>
                <span style={{ fontSize: '11px', color: '#6366f1', fontWeight: 800 }}>X-STEP (PAN)</span>
                <div style={{ display: 'flex', gap: '5px', marginTop: '5px' }}>
                  {[1, 5, 10].map(v => (
                    <button key={v} onClick={() => setStepX(v)} style={{ flex: 1, padding: '8px', background: stepX === v ? '#4f46e5' : '#2a2a3d', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>{v}</button>
                  ))}
                </div>
              </div>
              <div style={stepBoxStyle}>
                <span style={{ fontSize: '11px', color: '#10b981', fontWeight: 800 }}>Z-STEP (TILT)</span>
                <div style={{ display: 'flex', gap: '5px', marginTop: '5px' }}>
                  {[1, 5, 10].map(v => (
                    <button key={v} onClick={() => setStepZ(v)} style={{ flex: 1, padding: '8px', background: stepZ === v ? '#059669' : '#2a2a3d', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>{v}</button>
                  ))}
                </div>
              </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '15px' }}>
            <button onClick={toggleDetection} style={{ ...actionBtnStyle, background: isDetecting ? '#059669' : '#374151', fontSize: '12px' }}>
              {isDetecting ? "👁️ AI DETECTION: ON" : "👁️ AI DETECTION: OFF"}
            </button>
            <button onClick={toggleTracking} style={{ ...actionBtnStyle, background: isAutoTracking ? '#059669' : '#374151', fontSize: '12px' }}>
              {isAutoTracking ? "🤖 AUTO TRACKING: ON" : "🤖 AUTO TRACKING: OFF"}
            </button>
          </div>

          <div style={cmdLogStyle}>
            <span style={{ fontSize: '10px', color: '#555' }}>LAST CMD: </span>
            <span style={{ color: '#10b981', fontFamily: 'monospace' }}>{lastCmd}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// 스타일 정의 (기존과 동일)
const videoWrapperStyle = { position: 'relative', background: '#000', borderRadius: '20px', overflow: 'hidden', width: '45%', aspectRatio: '1/1', border: '1px solid #2a2a3a' };
const videoImgStyle = { width: '100%', height: '100%', objectFit: 'cover' };
const coordBoxStyle = { background: 'rgba(22,22,37,0.8)', padding: '15px 25px', borderRadius: '20px', border: '1px solid #2a2a3a', textAlign: 'center' };
const controlPanelStyle = { flexShrink: 0, width: '380px', background: '#161625', padding: '20px', borderRadius: '32px', border: '1px solid #2a2a3a' };
const stepBoxStyle = { background: '#0a0a12', padding: '10px', borderRadius: '12px', border: '1px solid #222' };
const cmdLogStyle = { padding: '12px', background: '#000', borderRadius: '14px', border: '1px solid #333', fontSize: '11px' };
const actionBtnStyle = { width: '100%', padding: '12px', color: '#fff', border: 'none', borderRadius: '12px', cursor: 'pointer', fontWeight: '800' };

const Btn = ({ text, onClick, bg = '#2a2a4a', active = false }) => (
  <button onClick={onClick}
    style={{ width: '75px', height: '75px', background: active ? '#312e81' : bg, color: '#fff', border: 'none', borderRadius: '22px', cursor: 'pointer', fontSize: '26px', boxShadow: '0 5px 0 #000' }}
    onMouseDown={(e) => { e.currentTarget.style.transform = 'translateY(4px)'; e.currentTarget.style.boxShadow = '0 1px 0 #000'; }}
    onMouseUp={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 5px 0 #000'; }}>
    {text}
  </button>
);