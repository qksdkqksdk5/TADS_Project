/* eslint-disable 브랜치 테스트*/
import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';

export default function RaspiModule() {
  const [panPos,          setPanPos]          = useState(0);
  const [tiltPos,         setTiltPos]         = useState(0);
  const [lastCmd,         setLastCmd]         = useState("READY");
  const [step,            setStep]            = useState(10);
  const [isConnecting,    setIsConnecting]    = useState(true);
  const [isFlipped,       setIsFlipped]       = useState(false);
  const [isDetecting,     setIsDetecting]     = useState(false);
  const [isAutoTracking,  setIsAutoTracking]  = useState(false);
  const [fireAlert,       setFireAlert]       = useState(false);
  const [streamKey,       setStreamKey]       = useState(Date.now());
  const [isCombinedMode,  setIsCombinedMode]  = useState(false);

  // ✅ 렌더마다 재생성되지 않도록 ref로 고정
  const RASPI_IP = "192.168.219.155";
  // const BASE_URL = useRef(`http://${window.location.hostname}:5000/api/raspi`).current;
  const BASE_URL = useRef(`https://with-guitar-power-ferry.trycloudflare.com/api/raspi`).current;

  // ✅ video URL도 ref로 관리 — streamKey state 변경이 useEffect 재실행 유발 안 하도록
  const normalVideoUrl  = useRef(`http://${RASPI_IP}:5000/video_feed`);
  const thermalVideoUrl = useRef(`${BASE_URL}/video_feed`);

  const handleStreamError = useCallback(() => {
    const t = Date.now();
    normalVideoUrl.current  = `http://${RASPI_IP}:5000/video_feed?t=${t}`;
    thermalVideoUrl.current = `${BASE_URL}/video_feed?t=${t}`;
    setStreamKey(t); // img를 key로 재마운트하기 위해서만 사용
  }, []);

  // ✅ 의존성 없음 — 마운트 시 딱 한 번만 생성, BASE_URL은 closure로 캡처
  const fetchStatus = useCallback(async (gcode = null, mode = null) => {
    try {
      const params = {};
      if (gcode) params.cmd  = gcode;
      if (mode)  params.mode = mode;
      const response = await axios.get(`${BASE_URL}/control`, { params, timeout: 2000 });
      if (response.data) {
        setFireAlert(!!response.data.fire_alert);
        setIsAutoTracking(!!response.data.auto);
        setIsDetecting(!!response.data.detect);
        if (gcode) setLastCmd(gcode);
      }
      setIsConnecting(false);
    } catch (err) {
      setIsConnecting(true);
    }
  }, []); // ✅ 의존성 배열 비움

  // ✅ 의존성 없음 — 마운트/언마운트 시 딱 한 번만 실행
  useEffect(() => {
    axios.post(`${BASE_URL}/start`).catch(() => {});

    const init = async () => {
      await fetchStatus("M211 S0");
      await fetchStatus("M17");
      await fetchStatus("G91");
    };
    init();

    const timer = setInterval(() => fetchStatus(), 1000);

    return () => {
      clearInterval(timer);
      axios.post(`${BASE_URL}/stop`).catch(() => {});
    };
  }, []); // ✅ 의존성 배열 비움

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
      flex: 1, padding: '20px 40px', minHeight: '100vh', fontFamily: 'Inter, sans-serif', transition: '0.5s',
      background: fireAlert ? '#4a0000' : '#0a0a12', color: '#e0e0ff'
    }}>
      {fireAlert && (
        <div style={alertBannerStyle}>🚨 EMERGENCY: FIRE / EXTREME HEAT DETECTED 🚨</div>
      )}

      <header style={{ marginBottom: '30px', textAlign: 'center' }}>
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

      <div style={{ display: 'flex', gap: '30px', justifyContent: 'center', alignItems: 'flex-start' }}>
        {/* 좌측: 듀얼 영상 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'flex', gap: '20px' }}>
            <div style={videoWrapperStyle}>
              <span style={videoLabelStyle}>RGB CAMERA (RPI ORIGIN)</span>
              {/* ✅ key prop으로 재마운트 — src 문자열 변경 대신 img 엘리먼트 자체를 교체 */}
              <img
                key={`normal-${streamKey}`}
                src={normalVideoUrl.current}
                onError={handleStreamError}
                style={{ ...videoImgStyle, transform: isFlipped ? 'rotate(180deg)' : 'rotate(0deg)' }}
                crossOrigin="anonymous"
              />
            </div>

            <div style={{ ...videoWrapperStyle, border: fireAlert ? '3px solid #ff4444' : '1px solid #2a2a3a' }}>
              <span style={{ ...videoLabelStyle, color: '#fca5a5' }}>THERMAL SENSOR (ANALYSIS)</span>
              <img
                key={`thermal-${streamKey}`}
                src={thermalVideoUrl.current}
                onError={handleStreamError}
                style={{ ...videoImgStyle, transform: isFlipped ? 'rotate(180deg)' : 'rotate(0deg)', filter: 'contrast(1.1) brightness(1.1)' }}
                crossOrigin="anonymous"
              />
              {fireAlert && <div style={heatOverlayStyle}>⚠️ HEAT</div>}
            </div>
          </div>

          <div style={coordBoxStyle}>
            <span style={{ fontSize: '12px', color: '#818cf8', fontWeight: 800 }}>PAN/TILT COORDINATES</span>
            <div style={{ fontSize: '20px', fontFamily: 'monospace', fontWeight: 600 }}>X: {panPos} | Y: {tiltPos}</div>
          </div>
        </div>

        {/* 우측: 제어 패널 */}
        <div style={controlPanelStyle}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '30px' }}>
            <button onClick={toggleDetection} style={{ ...actionBtnStyle, background: isDetecting ? '#059669' : '#374151' }}>
              {isDetecting ? "🟢 AI 감지 활성" : "⚪ AI 감지 켜기"}
            </button>
            <button onClick={toggleTracking} disabled={!isDetecting} style={{ ...actionBtnStyle, background: isAutoTracking ? '#ef4444' : '#1e1b4b', opacity: isDetecting ? 1 : 0.5 }}>
              {isAutoTracking ? "🛑 자동 추적 중지" : "🔍 열원 자동 추적"}
            </button>
          </div>

          <div style={{ marginBottom: '30px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 85px)', gap: '15px', justifyContent: 'center' }}>
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

          <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
            <div style={stepBoxStyle}>
              <span style={{ fontSize: '12px', color: '#6366f1', fontWeight: 800 }}>STEP SIZE</span>
              <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                {[1, 10, 50].map(v => (
                  <button key={v} onClick={() => setStep(v)} style={{ flex: 1, padding: '12px', background: step === v ? '#4f46e5' : '#2a2a3d', color: '#fff', border: 'none', borderRadius: '12px', cursor: 'pointer', fontWeight: 'bold' }}>{v}</button>
                ))}
              </div>
            </div>
            <button onClick={() => setIsFlipped(!isFlipped)} style={{ ...actionBtnStyle, background: '#2e2e42', padding: '12px' }}>🔄 화면 반전 (Flip)</button>
            <div style={cmdLogStyle}>
              <span style={{ fontSize: '10px', color: '#555' }}>LAST CMD: </span>
              <span style={{ color: '#10b981', fontFamily: 'monospace' }}>{lastCmd}</span>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
      `}</style>
    </div>
  );
}

const videoWrapperStyle = { position: 'relative', width: '480px', height: '360px', background: '#000', borderRadius: '20px', overflow: 'hidden', boxShadow: '0 10px 30px rgba(0,0,0,0.5)', border: '1px solid #2a2a3a' };
const videoImgStyle     = { width: '100%', height: '100%', objectFit: 'cover', transition: '0.3s' };
const videoLabelStyle   = { position: 'absolute', top: '15px', left: '15px', background: 'rgba(0,0,0,0.7)', padding: '4px 12px', borderRadius: '8px', fontSize: '11px', fontWeight: 'bold', zIndex: 10 };
const heatOverlayStyle  = { position: 'absolute', top: '15px', right: '15px', background: '#ff0000', color: '#fff', padding: '4px 10px', borderRadius: '6px', fontSize: '12px', fontWeight: '900', animation: 'blink 0.6s infinite' };
const alertBannerStyle  = { background: '#ff0000', color: '#fff', padding: '15px', borderRadius: '12px', marginBottom: '20px', fontWeight: '900', fontSize: '22px', textAlign: 'center', animation: 'blink 0.8s infinite', boxShadow: '0 0 20px rgba(255,0,0,0.4)' };
const modeBtnStyle      = { padding: '8px 20px', borderRadius: '50px', background: 'transparent', cursor: 'pointer', fontWeight: 'bold', transition: '0.3s' };
const coordBoxStyle     = { background: 'rgba(22,22,37,0.8)', padding: '15px 25px', borderRadius: '20px', border: '1px solid #2a2a3a', textAlign: 'center' };
const controlPanelStyle = { flex: '1', maxWidth: '400px', background: '#161625', padding: '30px', borderRadius: '32px', border: '1px solid #2a2a3a' };
const stepBoxStyle      = { background: '#0a0a12', padding: '15px', borderRadius: '16px', border: '1px solid #222' };
const cmdLogStyle       = { padding: '12px', background: '#000', borderRadius: '14px', border: '1px solid #333', fontSize: '12px' };
const actionBtnStyle    = { width: '100%', padding: '18px', color: '#fff', border: 'none', borderRadius: '16px', cursor: 'pointer', fontWeight: '800', transition: '0.2s' };

const Badge = ({ color, text }) => (
  <div style={{ padding: '6px 16px', background: 'rgba(255,255,255,0.05)', borderRadius: '50px', border: `1px solid ${color}`, fontSize: '12px', color: color, fontWeight: 'bold' }}>● {text}</div>
);

const Btn = ({ text, onClick, bg = '#2a2a4a', active = false }) => (
  <button onClick={onClick}
    style={{ width: '85px', height: '85px', background: active ? '#312e81' : bg, color: '#fff', border: 'none', borderRadius: '22px', cursor: 'pointer', fontSize: '28px', boxShadow: '0 6px 0 #000', transition: '0.1s' }}
    onMouseDown={(e) => { e.currentTarget.style.transform = 'translateY(4px)'; e.currentTarget.style.boxShadow = '0 2px 0 #000'; }}
    onMouseUp={(e)   => { e.currentTarget.style.transform = 'translateY(0)';   e.currentTarget.style.boxShadow = '0 6px 0 #000'; }}>
    {text}
  </button>
);