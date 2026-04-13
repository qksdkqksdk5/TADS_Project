/* eslint-disable */
// src/modules/monitoring/components/CctvPlayer.jsx
import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

const POLL_MS      = 500;
const NORMAL_COLOR = '#22c55e';
const WRONG_COLOR  = '#ef4444';
const LEVEL_LABEL  = { SMOOTH: '원활', SLOW: '서행', CONGESTED: '정체', JAM: '정체' };
const LEVEL_COLOR  = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function CctvPlayer({ host, cameraId, cameraData, itsCctv }) {
  // itsCctv = { camera_id, name, url, ... } | null
  // itsCctv가 있으면 HLS 모드, 없으면 기존 MJPEG 모드

  const source = itsCctv ? 'its' : (cameraId ? 'monitoring' : null);

  return (
    <div style={{
      height: '100%', position: 'relative', background: '#000',
      borderRadius: '12px', overflow: 'hidden',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {source === null && <Placeholder icon="📡" text="구간을 선택하세요" />}
      {source === 'its'        && <ItsProxyPlayer host={host} cam={itsCctv} />}
      {source === 'monitoring' && <MjpegPlayer host={host} cameraId={cameraId} cameraData={cameraData} />}
    </div>
  );
}

// ── ITS CCTV 보기 전용 (백엔드 MJPEG 프록시) ─────────────────
// 브라우저에서 ITS URL 직접 접근 시 403이므로, 백엔드가 대신 열어 MJPEG로 변환
function ItsProxyPlayer({ host, cam }) {
  const [imgError, setImgError] = useState(false);
  const [streamKey, setStreamKey] = useState(0);

  // cam 변경 시 스트림 재시작
  useEffect(() => {
    setImgError(false);
    setStreamKey(k => k + 1);
  }, [cam?.camera_id]);

  if (!cam) return <Placeholder icon="📷" text="카메라를 선택하세요" />;

  const proxyUrl = `http://${host}:5000/api/monitoring/its/view_feed`
    + `?camera_id=${encodeURIComponent(cam.camera_id)}`
    + `&url=${encodeURIComponent(cam.url)}`;

  return (
    <>
      {imgError && <Placeholder icon="⏳" text="스트림 연결 중..." />}
      <img
        key={streamKey}
        src={proxyUrl}
        alt="ITS CCTV"
        onError={() => setImgError(true)}
        onLoad={()  => setImgError(false)}
        style={{
          width: '100%', height: '100%',
          objectFit: 'contain',
          display: imgError ? 'none' : 'block',
        }}
      />
      {!imgError && cam.name && (
        <div style={{
          position: 'absolute', top: '8px', left: '8px',
          background: 'rgba(2,6,23,0.78)', borderRadius: '6px',
          padding: '5px 10px', fontSize: '11px', color: '#94a3b8',
          display: 'flex', alignItems: 'center', gap: '6px',
        }}>
          <span style={{ color: '#3b82f6' }}>📷 ITS</span>
          <span>{cam.name}</span>
        </div>
      )}
    </>
  );
}

// ── MJPEG 플레이어 (모니터링 카메라 AI 분석 영상) ─────────────
function MjpegPlayer({ host, cameraId, cameraData }) {
  const imgRef    = useRef(null);
  const canvasRef = useRef(null);
  const tracksRef = useRef([]);
  const rafRef    = useRef(null);
  const [imgError,  setImgError]  = useState(false);
  const [streamKey, setStreamKey] = useState(0);

  const streamUrl = `http://${host}:5000/api/monitoring/video_feed/${cameraId}`;

  useEffect(() => {
    tracksRef.current = [];
    setImgError(false);
    setStreamKey(k => k + 1);
  }, [cameraId]);

  // 바운딩박스 폴링
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const res = await axios.get(
          `http://${host}:5000/api/monitoring/tracks/${cameraId}`,
          { timeout: 400 },
        );
        tracksRef.current = Array.isArray(res.data) ? res.data : [];
      } catch {}
    }, POLL_MS);
    return () => clearInterval(poll);
  }, [host, cameraId]);

  // RAF 그리기 루프
  useEffect(() => {
    const draw = () => {
      const img    = imgRef.current;
      const canvas = canvasRef.current;
      if (img && canvas) {
        const dw = img.clientWidth;
        const dh = img.clientHeight;
        if (dw > 0 && dh > 0) {
          if (canvas.width  !== dw) canvas.width  = dw;
          if (canvas.height !== dh) canvas.height = dh;
          const ctx = canvas.getContext('2d');
          ctx.clearRect(0, 0, dw, dh);
          const nw = img.naturalWidth  || dw;
          const nh = img.naturalHeight || dh;
          const scale = Math.min(dw / nw, dh / nh);
          const dispW = nw * scale;
          const dispH = nh * scale;
          const offX  = (dw - dispW) / 2;
          const offY  = (dh - dispH) / 2;
          tracksRef.current.forEach(t => {
            const x1 = t.x1 * scale + offX;
            const y1 = t.y1 * scale + offY;
            const w  = (t.x2 - t.x1) * scale;
            const h  = (t.y2 - t.y1) * scale;
            if (t.is_wrongway) {
              ctx.strokeStyle = WRONG_COLOR; ctx.lineWidth = 3;
              ctx.strokeRect(x1, y1, w, h);
              ctx.fillStyle = WRONG_COLOR;
              ctx.font = 'bold 11px sans-serif';
              ctx.fillText(`⚠️ ${t.id}`, x1 + 2, y1 > 16 ? y1 - 4 : y1 + h + 12);
            } else {
              ctx.strokeStyle = NORMAL_COLOR; ctx.lineWidth = 1.5;
              ctx.strokeRect(x1, y1, w, h);
            }
          });
        }
      }
      rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  const { is_learning, relearning, waiting_stable, learning_progress, learning_total, level, jam_score } =
    cameraData || {};

  return (
    <>
      {imgError && <Placeholder icon="⏳" text="연결 대기 중..." />}
      <img
        key={streamKey}
        ref={imgRef}
        src={streamUrl}
        alt="CCTV"
        onError={() => setImgError(true)}
        onLoad={()  => setImgError(false)}
        style={{ width: '100%', height: '100%', objectFit: 'contain', display: imgError ? 'none' : 'block' }}
      />
      {!imgError && (
        <canvas
          ref={canvasRef}
          style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
        />
      )}
      {!imgError && (
        <StatusOverlay
          is_learning={is_learning} relearning={relearning} waiting_stable={waiting_stable}
          learning_progress={learning_progress} learning_total={learning_total}
          level={level} jam_score={jam_score}
        />
      )}
    </>
  );
}

// ── 상태 오버레이 ─────────────────────────────────────────────
function StatusOverlay({ is_learning, relearning, waiting_stable, learning_progress, learning_total, level, jam_score }) {
  if (waiting_stable) {
    return <div style={overlayBase}><span style={{ fontSize: '11px', color: '#f97316', fontWeight: 600 }}>안정 대기중...</span></div>;
  }
  if (is_learning) {
    const pct = learning_total
      ? Math.min(Math.round((learning_progress / learning_total) * 100), 100) : 0;
    return (
      <div style={overlayBase}>
        <div style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 600 }}>
          학습 중... ({learning_progress}/{learning_total})
        </div>
        <div style={{ background: '#1e293b', borderRadius: '3px', height: '4px', marginTop: '5px', width: '120px' }}>
          <div style={{ height: '100%', width: `${pct}%`, background: '#38bdf8', borderRadius: '3px', transition: 'width 0.5s' }} />
        </div>
      </div>
    );
  }
  if (relearning) {
    return <div style={overlayBase}><span style={{ fontSize: '11px', color: '#f97316', fontWeight: 600 }}>재보정 중...</span></div>;
  }
  if (!level) return null;
  return (
    <div style={{ ...overlayBase, flexDirection: 'row', gap: '8px' }}>
      <span style={{ fontSize: '11px', fontWeight: 700, color: LEVEL_COLOR[level] || '#6b7280' }}>
        [{LEVEL_LABEL[level] || level}]
      </span>
      <span style={{ fontSize: '11px', color: '#94a3b8' }}>jam: {(jam_score ?? 0).toFixed(2)}</span>
    </div>
  );
}

// ── 플레이스홀더 ──────────────────────────────────────────────
function Placeholder({ icon, text }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#334155', fontSize: '12px' }}>
      <span style={{ fontSize: '28px' }}>{icon}</span>
      {text}
    </div>
  );
}

const overlayBase = {
  position: 'absolute', top: '8px', left: '8px',
  background: 'rgba(2,6,23,0.78)', borderRadius: '6px',
  padding: '6px 10px', display: 'flex', flexDirection: 'column',
};
