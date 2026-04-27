/* eslint-disable 브랜치 테스트*/
import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

export default function RaspiModule({host}) {
  const clientId = useRef(Math.random().toString(36).substring(7)).current;

  const [panPos, setPanPos] = useState(0);
  const [tiltPos, setTiltPos] = useState(0);
  const [lastCmd, setLastCmd] = useState("READY");
  const [step, setStep] = useState(10);
  const [isConnecting, setIsConnecting] = useState(true);
  const [isDetecting, setIsDetecting] = useState(false);
  const [isAutoTracking, setIsAutoTracking] = useState(false);
  const [fireAlert, setFireAlert] = useState(false);
  const [streamKey, setStreamKey] = useState(Date.now());
  const [isCombinedMode, setIsCombinedMode] = useState(false);
  const [motorEnabled, setMotorEnabled] = useState(false);

  const BACKEND_HOST = host || window.location.hostname;
  const BASE_URL = `https://${BACKEND_HOST}/api/raspi`;

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

      const response = await client.get(url, { timeout: 2500 });
      if (response.data && gcode) {
        setLastCmd(gcode);
        if (gcode === "M17") setMotorEnabled(true);
        if (gcode === "M18") setMotorEnabled(false);
      }
      setIsConnecting(false);
    } catch (err) {
      if (err.response && err.response.status === 403) {
        alert(err.response.data.message);
      } else {
        setIsConnecting(true);
      }
    }
  }, [client, clientId]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const startSystem = async () => {
      try {
        await client.post(`/start`);
        await new Promise(r => setTimeout(r, 1000));
        await fetchStatus("M17");
        await new Promise(r => setTimeout(r, 500));
        await fetchStatus("M211 S0");
        await new Promise(r => setTimeout(r, 500));
        await fetchStatus("G91"); 
      } catch (err) { console.error("❌ Initialization failed", err); }
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
    const gcode = `G1 ${x !== 0 ? `X${x} ` : ""}${y !== 0 ? `Y${y} ` : ""}F100`;
    fetchStatus(gcode);
    setPanPos(p => p + x);
    setTiltPos(p => p + y);
  };

  const toggleDetection = () => fetchStatus(null, isDetecting ? "detect_off" : "detect_on");
  const toggleTracking  = () => fetchStatus(null, isAutoTracking ? "auto_off" : "auto_on");

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100vh', padding: '20px 40px', boxSizing: 'border-box',
      fontFamily: 'Inter, sans-serif', transition: '0.5s', overflow: 'hidden', // 스크롤 제거
      background: fireAlert ? '#4a0000' : '#0a0a12', color: '#e0e0ff'
    }}>
      {fireAlert && (
        <div style={alertBannerStyle}>🚨 EMERGENCY: FIRE / EXTREME HEAT DETECTED 🚨</div>
      )}

      {/* 헤더 부분 (원본 디자인) */}
      <header style={{ marginBottom: '20px', textAlign: 'center', flexShrink: 0 }}>
        <h1 style={{ fontSize: '32px', fontWeight: 800, letterSpacing: '-1px', margin: 0 }}>AI DUAL-VISION MONITORING</h1>
        <div style={{ marginTop: '15px', display: 'flex', justifyContent: 'center', gap: '15px' }}>
          <Badge color={isConnecting ? '#f59e0b' : '#10b981'} text={isConnecting ? 'RECONNECTING' : 'SYSTEM LIVE'} />
          <button
            onClick={() => setIsCombinedMode(!isCombinedMode)}
            style={{ ...modeBtnStyle, border: `2px solid ${isCombinedMode ? '#6366f1' : '#4b5563'}`, color: isCombinedMode ? '#818cf8' : '#9ca3af' }}
          >
            {isCombinedMode ? "💠 AI 분석 모드 활성" : "🔁 순수 데이터 모드"}
          </button>
        </div>
      </header>

      {/* 중앙 본문 영역 */}
      <div style={{ display: 'flex', gap: '0px', justifyContent: 'center', alignItems: 'center', flex: 1, minHeight: 0 }}>
        
        {/* 왼쪽: 영상 및 좌표 (영상을 85% 크기로 제한하여 10% 축소 효과) */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '50px', flex: 1, height: '100%' }}>
          <div style={{ display: 'flex', gap: '20px', height: '70%', width: '100%', justifyContent: 'center', alignItems: 'center' }}>
            <div style={videoWrapperStyle}>
              <span style={videoLabelStyle}>RGB CAMERA (RPI ORIGIN)</span>
              <img key={`normal-${streamKey}`} src={videoUrls.normal} onError={handleStreamError} style={videoImgStyle} alt="Normal" />
            </div>
            <div style={{ ...videoWrapperStyle, border: fireAlert ? '3px solid #ff4444' : '1px solid #2a2a3a' }}>
              <span style={{ ...videoLabelStyle, color: '#fca5a5' }}>THERMAL SENSOR (ANALYSIS)</span>
              <img key={`thermal-${streamKey}`} src={videoUrls.thermal} onError={handleStreamError} style={{ ...videoImgStyle, filter: 'contrast(1.1) brightness(1.1)' }} alt="Thermal" />
              {fireAlert && <div style={heatOverlayStyle}>⚠️ HEAT</div>}
            </div>
          </div>
          
          <div style={coordBoxStyle}>
            <span style={{ fontSize: '12px', color: '#818cf8', fontWeight: 800 }}>PAN/TILT COORDINATES</span>
            <div style={{ fontSize: '20px', fontFamily: 'monospace', fontWeight: 600 }}>X: {panPos} | Y: {tiltPos}</div>
          </div>
        </div>

        {/* 오른쪽: 제어 패널 (원본 디자인 유지, 스크롤 방지를 위해 내부 여백만 미세 조정) */}
        <div style={controlPanelStyle}>
          <div style={sectionBoxStyle}>
            <span style={{ fontSize: '12px', color: '#818cf8', fontWeight: 800 }}>MOTOR POWER</span>
            <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
              <button onClick={() => fetchStatus("M17")} style={{ ...pwrBtnStyle, background: motorEnabled ? '#10b981' : '#1f2937', border: motorEnabled ? '2px solid #34d399' : '1px solid #374151' }}>
                🔓 ENABLE (M17)
              </button>
              <button onClick={() => fetchStatus("M18")} style={{ ...pwrBtnStyle, background: !motorEnabled ? '#ef4444' : '#1f2937', border: !motorEnabled ? '2px solid #f87171' : '1px solid #374151' }}>
                🔒 DISABLE (M18)
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
            <button onClick={toggleDetection} style={{ ...actionBtnStyle, background: isDetecting ? '#059669' : '#374151' }}>
              {isDetecting ? "🟢 AI 감지 활성" : "⚪ AI 감지 켜기"}
            </button>
            <button onClick={toggleTracking} disabled={!isDetecting} style={{ ...actionBtnStyle, background: isAutoTracking ? '#ef4444' : '#1e1b4b', opacity: isDetecting ? 1 : 0.5 }}>
              {isAutoTracking ? "🛑 자동 추적 중지" : "🔍 열원 자동 추적"}
            </button>
          </div>

          <div style={{ marginBottom: '20px' }}>
            {/* 버튼 크기를 85px -> 75px로 줄여서 세로 스크롤만 없앰 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 75px)', gap: '15px', justifyContent: 'center' }}>
              <Btn text="↖" onClick={() => move(-step, step)} />
              <Btn text="▲" onClick={() => move(0, step)} active />
              <Btn text="↗" onClick={() => move(step, step)} />
              <Btn text="◀" onClick={() => move(-step, 0)} active />
              <Btn text="🏠" bg="#f59e0b" onClick={() => { fetchStatus(`G1 X${-panPos} Y${-tiltPos} F100`); setPanPos(0); setTiltPos(0); }} />
              <Btn text="▶" onClick={() => move(step, 0)} active />
              <Btn text="↙" onClick={() => move(-step, -step)} />
              <Btn text="▼" onClick={() => move(0, -step)} active />
              <Btn text="↘" onClick={() => move(step, -step)} />
            </div>
          </div>

          <div style={{ marginBottom: '15px' }}>
             <div style={stepBoxStyle}>
                <span style={{ fontSize: '12px', color: '#6366f1', fontWeight: 800 }}>STEP SIZE</span>
                <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                  {[1, 10, 50].map(v => (
                    <button key={v} onClick={() => setStep(v)} style={{ flex: 1, padding: '12px', background: step === v ? '#4f46e5' : '#2a2a3d', color: '#fff', border: 'none', borderRadius: '12px', cursor: 'pointer', fontWeight: 'bold' }}>{v}</button>
                  ))}
                </div>
              </div>
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

// 🎨 작성자님의 완벽한 원본 스타일 그대로 복구! (레이아웃 조절용 속성만 일부 추가)
const videoWrapperStyle = { position: 'relative', background: '#000', borderRadius: '20px', overflow: 'hidden', boxShadow: '0 10px 30px rgba(0,0,0,0.5)', border: '1px solid #2a2a3a', aspectRatio: '1/1', maxHeight: '100%' };
const videoImgStyle     = { width: '100%', height: '100%', objectFit: 'cover', transition: '0.3s' };
const videoLabelStyle   = { position: 'absolute', top: '15px', left: '15px', background: 'rgba(0,0,0,0.7)', padding: '4px 12px', borderRadius: '8px', fontSize: '11px', fontWeight: 'bold', zIndex: 10 };
const heatOverlayStyle  = { position: 'absolute', top: '15px', right: '15px', background: '#ff0000', color: '#fff', padding: '4px 10px', borderRadius: '6px', fontSize: '12px', fontWeight: '900', animation: 'blink 0.6s infinite' };
const alertBannerStyle  = { background: '#ff0000', color: '#fff', padding: '15px', borderRadius: '12px', marginBottom: '20px', fontWeight: '900', fontSize: '22px', textAlign: 'center', animation: 'blink 0.8s infinite', boxShadow: '0 0 20px rgba(255,0,0,0.4)' };
const modeBtnStyle      = { padding: '8px 20px', borderRadius: '50px', background: 'transparent', cursor: 'pointer', fontWeight: 'bold', transition: '0.3s' };
const coordBoxStyle     = { background: 'rgba(22,22,37,0.8)', padding: '15px 25px', borderRadius: '20px', border: '1px solid #2a2a3a', textAlign: 'center' };
// 우측 패널만 100vh에 쏙 들어가도록 폭과 여백 미세 조절
const controlPanelStyle = { flexShrink: 0, width: '380px', background: '#161625', padding: '25px', borderRadius: '32px', border: '1px solid #2a2a3a' };
const stepBoxStyle      = { background: '#0a0a12', padding: '15px', borderRadius: '16px', border: '1px solid #222' };
const cmdLogStyle       = { padding: '12px', background: '#000', borderRadius: '14px', border: '1px solid #333', fontSize: '12px' };
const actionBtnStyle    = { width: '100%', padding: '15px', color: '#fff', border: 'none', borderRadius: '16px', cursor: 'pointer', fontWeight: '800', transition: '0.2s' };
const sectionBoxStyle   = { background: '#0a0a12', padding: '15px', borderRadius: '16px', border: '1px solid #222', marginBottom: '15px' };
const pwrBtnStyle       = { flex: 1, padding: '12px', borderRadius: '10px', color: '#fff', cursor: 'pointer', fontWeight: 'bold', fontSize: '13px', transition: '0.2s' };

const Badge = ({ color, text }) => (
  <div style={{ padding: '6px 16px', background: 'rgba(255,255,255,0.05)', borderRadius: '50px', border: `1px solid ${color}`, fontSize: '12px', color: color, fontWeight: 'bold' }}>● {text}</div>
);

// 그림자 및 3D 클릭 효과 완벽 유지 (버튼 픽셀 크기만 75px로 축소)
const Btn = ({ text, onClick, bg = '#2a2a4a', active = false }) => (
  <button onClick={onClick}
    style={{ width: '75px', height: '75px', background: active ? '#312e81' : bg, color: '#fff', border: 'none', borderRadius: '22px', cursor: 'pointer', fontSize: '26px', boxShadow: '0 5px 0 #000', transition: '0.1s' }}
    onMouseDown={(e) => { e.currentTarget.style.transform = 'translateY(4px)'; e.currentTarget.style.boxShadow = '0 1px 0 #000'; }}
    onMouseUp={(e)   => { e.currentTarget.style.transform = 'translateY(0)';   e.currentTarget.style.boxShadow = '0 5px 0 #000'; }}>
    {text}
  </button>
);