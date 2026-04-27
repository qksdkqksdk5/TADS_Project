/* eslint-disable */
// src/modules/monitoring/components/CctvPlayer.jsx
import { useEffect, useRef, useState } from 'react';
import axios from 'axios';

const POLL_MS      = 500;    // 바운딩박스 폴링 주기 (ms)
const NORMAL_COLOR = '#22c55e';  // 정상 차량 색
const WRONG_COLOR  = '#ef4444';  // 역주행 차량 색
const LEVEL_LABEL  = { SMOOTH: '원활', SLOW: '서행', CONGESTED: '정체', JAM: '정체' };
const LEVEL_COLOR  = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };

// ItsProxyPlayer 이미지 오류 후 자동 재시도까지 대기 시간 (ms)
const ITS_AUTO_RETRY_MS = 5000;

// ── 메인 컴포넌트 ─────────────────────────────────────────────
// streamStatus: useMonitoringSocket의 streamFailures[cameraId] — 연결 실패 정보
// onRestartCamera: "다시 시도" 버튼 클릭 시 호출할 콜백 (camera_id를 인자로 받음)
export default function CctvPlayer({ host, cameraId, cameraData, itsCctv, streamStatus, onRestartCamera }) {
  // itsCctv = { camera_id, name, url, ... } | null
  // itsCctv가 있으면 ITS 프록시 모드, 없으면 MJPEG(AI 분석) 모드

  const source = itsCctv ? 'its' : (cameraId ? 'monitoring' : null);

  return (
    <div style={{
      height: '100%', position: 'relative', background: '#000',
      borderRadius: '12px', overflow: 'hidden',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {source === null && <Placeholder icon="📡" text="구간을 선택하세요" />}
      {source === 'its'        && <ItsProxyPlayer host={host} cam={itsCctv} />}
      {source === 'monitoring' && (
        <MjpegPlayer
          host={host}
          cameraId={cameraId}
          cameraData={cameraData}
          streamStatus={streamStatus}
          onRestartCamera={onRestartCamera}
        />
      )}
    </div>
  );
}

// ── ITS CCTV 보기 전용 (백엔드 MJPEG 프록시) ─────────────────
// 브라우저에서 ITS URL 직접 접근 시 403이므로, 백엔드가 대신 열어 MJPEG로 변환
function ItsProxyPlayer({ host, cam }) {
  const [imgError,  setImgError]  = useState(false);  // 이미지 로드 실패 여부
  const [streamKey, setStreamKey] = useState(0);       // 이미지 src 변경으로 재시작 트리거

  // cam 변경 시 에러 상태 초기화 및 스트림 재시작
  useEffect(() => {
    setImgError(false);
    setStreamKey(k => k + 1);
  }, [cam?.camera_id]);

  // 이미지 로드 오류 시 ITS_AUTO_RETRY_MS(5초) 후 자동으로 스트림을 다시 요청한다.
  // ITS 서버가 일시적으로 끊겼다가 복구되는 경우를 처리하기 위함이다.
  useEffect(() => {
    if (!imgError) return;                          // 오류 상태가 아니면 타이머 불필요
    const timer = setTimeout(() => {
      setImgError(false);                           // 에러 UI 숨기기
      setStreamKey(k => k + 1);                     // img src 재요청 트리거
    }, ITS_AUTO_RETRY_MS);
    return () => clearTimeout(timer);               // 언마운트 또는 cam 변경 시 타이머 취소
  }, [imgError]);

  if (!cam) return <Placeholder icon="📷" text="카메라를 선택하세요" />;

  // const proxyUrl = `https://${host}/api/monitoring/its/view_feed`
  const proxyUrl = `http://${host}:5000/api/monitoring/its/view_feed`
    + `?camera_id=${encodeURIComponent(cam.camera_id)}`
    + `&url=${encodeURIComponent(cam.url)}`;

  return (
    <>
      {/* 오류 시 "재연결 중" 안내 — 5초 후 자동 재시도된다 */}
      {imgError && (
        <Placeholder
          icon="🔄"
          text={`스트림 재연결 중... (${ITS_AUTO_RETRY_MS / 1000}초 후 자동 재시도)`}
        />
      )}
      <img
        key={streamKey}
        src={proxyUrl}
        alt="ITS CCTV"
        onError={() => setImgError(true)}   // 오류 발생 → 안내 UI 표시 + 5초 후 재시도
        onLoad={() => setImgError(false)}   // 로드 성공 → 안내 UI 숨김
        style={{
          width: '100%', height: '100%',
          objectFit: 'contain',
          display: imgError ? 'none' : 'block',
        }}
      />
      {/* 카메라 이름 오버레이 — 정상 스트림 중에만 표시 */}
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
// streamStatus: { fail_count, next_retry_in } — 백엔드 연결 실패 정보 (없으면 undefined)
// onRestartCamera: "다시 시도" 버튼 클릭 시 호출 (camera_id를 인자로 받음)
function MjpegPlayer({ host, cameraId, cameraData, streamStatus, onRestartCamera }) {
  const imgRef    = useRef(null);
  const canvasRef = useRef(null);
  const tracksRef = useRef([]);
  const rafRef    = useRef(null);
  const [imgError,  setImgError]  = useState(false);
  const [streamKey, setStreamKey] = useState(0);

// <<<<<<< HEAD
//   // localhost/127.0.0.1이면 http, 외부 호스트면 https 사용
//   const proto = (host.startsWith('localhost') || host.startsWith('127.')) ? 'http' : 'https';
//   const streamUrl = `${proto}://${host}/api/monitoring/video_feed/${cameraId}`;
// =======
  // const streamUrl = `https://${host}/api/monitoring/video_feed/${cameraId}`;
  const streamUrl = `http://${host}:5000/api/monitoring/video_feed/${cameraId}`;
// >>>>>>> 330c99599c04dd624521b83664f8ac057c3177e9

  useEffect(() => {
    tracksRef.current = [];
    setImgError(false);
    setStreamKey(k => k + 1);
  }, [cameraId]);

  // 바운딩박스 폴링 + 서버 재시작 감지 → MJPEG 자동 재연결
  // tracks 요청이 실패(서버 다운)했다가 다시 성공하면 서버가 재시작된 것 → streamKey 올려서 img src 재요청
  useEffect(() => {
    let wasDown = false;
    const poll = setInterval(async () => {
      try {
        const res = await axios.get(
// <<<<<<< HEAD
//           `${(host.startsWith('localhost') || host.startsWith('127.')) ? 'http' : 'https'}://${host}/api/monitoring/tracks/${cameraId}`,
// =======
          // `https://${host}/api/monitoring/tracks/${cameraId}`,
          `http://${host}:5000/api/monitoring/tracks/${cameraId}`,
// >>>>>>> 330c99599c04dd624521b83664f8ac057c3177e9
          { timeout: 400 },
        );
        tracksRef.current = Array.isArray(res.data) ? res.data : [];
        if (wasDown) {
          wasDown = false;
          setImgError(false);
          setStreamKey(k => k + 1);
        }
      } catch {
        wasDown = true;
        tracksRef.current = [];
      }
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
            const color  = t.is_wrongway ? WRONG_COLOR : NORMAL_COLOR;
            const trail  = (t.trail || []).map(([px, py]) => [px * scale + offX, py * scale + offY]);
            const cx_    = t.cx * scale + offX;
            const cy_    = t.cy * scale + offY;

            // 궤적 선 (오래된 점은 투명, 최신 점은 불투명)
            // 연속 두 점의 거리가 화면 짧은 변의 8% 초과이면 해당 구간을 그리지 않는다.
            // → 신호 끊김 후 차량이 순간이동한 것처럼 보이는 긴 선(꼬리) 제거.
            if (trail.length >= 2) {
              const maxSeg = Math.min(dw, dh) * 0.08; // 순간이동 판정 거리 (픽셀)
              const maxSeg2 = maxSeg * maxSeg;         // 제곱 비교로 sqrt 생략
              for (let i = 1; i < trail.length; i++) {
                const dx = trail[i][0] - trail[i - 1][0];
                const dy = trail[i][1] - trail[i - 1][1];
                if (dx * dx + dy * dy > maxSeg2) continue; // 순간이동 구간 skip
                ctx.globalAlpha = (i / trail.length) * 0.85;
                ctx.strokeStyle = color;
                ctx.lineWidth   = 1.5;
                ctx.beginPath();
                ctx.moveTo(trail[i - 1][0], trail[i - 1][1]);
                ctx.lineTo(trail[i][0],     trail[i][1]);
                ctx.stroke();
              }
              ctx.globalAlpha = 1;
            }

            // 중앙점 (채운 원)
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(cx_, cy_, 4, 0, Math.PI * 2);
            ctx.fill();

            // 방향 화살표
            const vx = t.vx || 0, vy = t.vy || 0;
            const vmag = Math.sqrt(vx * vx + vy * vy);
            if (vmag > 0.1) {
              const arrowLen = 20;
              const ex = cx_ + vx * arrowLen;
              const ey = cy_ + vy * arrowLen;
              ctx.strokeStyle = color;
              ctx.lineWidth   = 2;
              ctx.beginPath();
              ctx.moveTo(cx_, cy_);
              ctx.lineTo(ex, ey);
              ctx.stroke();
              // 화살촉
              const headLen = 7;
              const angle   = Math.atan2(vy, vx);
              ctx.beginPath();
              ctx.moveTo(ex, ey);
              ctx.lineTo(ex - headLen * Math.cos(angle - Math.PI / 6), ey - headLen * Math.sin(angle - Math.PI / 6));
              ctx.moveTo(ex, ey);
              ctx.lineTo(ex - headLen * Math.cos(angle + Math.PI / 6), ey - headLen * Math.sin(angle + Math.PI / 6));
              ctx.stroke();
            }

            // 역주행 라벨
            if (t.is_wrongway) {
              ctx.fillStyle = color;
              ctx.font      = 'bold 11px sans-serif';
              ctx.fillText(`⚠️ ${t.id}`, cx_ + 6, cy_ - 6);
            }
          });
          ctx.globalAlpha = 1;
        }
      }
      rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  const { is_learning, relearning, waiting_stable, learning_progress, learning_total, level } =
    cameraData || {};

  return (
    <>
      {/* 이미지 오류 시: 백엔드 연결 실패 정보가 있으면 상세 안내, 없으면 기본 대기 안내 */}
      {imgError && !streamStatus && <Placeholder icon="⏳" text="연결 대기 중..." />}
      {imgError && streamStatus && (
        <StreamFailedOverlay
          failCount={streamStatus.fail_count}
          nextRetryIn={streamStatus.next_retry_in}
          onRetry={() => onRestartCamera?.(cameraId)}
        />
      )}
      <img
        key={streamKey}
        ref={imgRef}
        src={streamUrl}
        alt="CCTV"
        onError={() => {
          setImgError(true);
          setTimeout(() => setStreamKey(k => k + 1), 2000);  // 2초 후 자동 재시도
        }}
        onLoad={() => setImgError(false)}
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
          level={level}
        />
      )}
      {/* 연결 실패 상태인데 이미지는 표시 중인 경우(이전 캐시 프레임) — 우측 상단에 경고 배지 */}
      {!imgError && streamStatus && (
        <div style={{
          position: 'absolute', top: '8px', right: '8px',
          background: 'rgba(239,68,68,0.85)', borderRadius: '6px',
          padding: '4px 8px', fontSize: '11px', color: '#fff', fontWeight: 600,
        }}>
          ⚠ 재연결 중 ({streamStatus.fail_count}회 실패)
        </div>
      )}
    </>
  );
}

// ── 상태 오버레이 — 학습 상태와 정체 레벨만 표시 (jam_score 제거)
function StatusOverlay({ is_learning, relearning, waiting_stable, learning_progress, learning_total, level }) {
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
  // 원활이면 오버레이 없음 — 정상 상태에서 UI를 가리지 않도록
  if (!level || level === 'SMOOTH') return null;
  return (
    <div style={{ ...overlayBase, flexDirection: 'row', gap: '6px', alignItems: 'center' }}>
      <span style={{ fontSize: '11px', fontWeight: 700, color: LEVEL_COLOR[level] || '#6b7280' }}>
        [{LEVEL_LABEL[level] || level}]
      </span>
    </div>
  );
}

// ── 연결 실패 오버레이 ─────────────────────────────────────────
// 백엔드 camera_stream_failed 이벤트 수신 시 표시된다.
// failCount: 연속 실패 횟수, nextRetryIn: 다음 자동 재시도까지 남은 초
// onRetry: "다시 시도" 버튼 클릭 시 호출 (백엔드 restart_camera API 호출)
function StreamFailedOverlay({ failCount, nextRetryIn, onRetry }) {
  const [retrying, setRetrying] = useState(false);  // 재시작 요청 중 여부

  // "다시 시도" 버튼 클릭 → 백엔드 restart_camera API 호출
  const handleRetry = async () => {
    setRetrying(true);
    try {
      await onRetry?.();                             // onRestartCamera(cameraId) 호출
    } finally {
      setTimeout(() => setRetrying(false), 3000);    // 3초 후 버튼 다시 활성화
    }
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      gap: '12px', padding: '20px',
    }}>
      {/* 실패 아이콘 및 설명 */}
      <span style={{ fontSize: '32px' }}>📡</span>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '13px', color: '#ef4444', fontWeight: 700, marginBottom: '4px' }}>
          스트림 연결 실패 ({failCount}회)
        </div>
        <div style={{ fontSize: '11px', color: '#475569' }}>
          {nextRetryIn}초 후 자동 재시도 예정
        </div>
      </div>
      {/* 수동 재시작 버튼 — 자동 재시도를 기다리지 않고 즉시 시도할 때 사용 */}
      <button
        onClick={handleRetry}
        disabled={retrying}
        style={{
          padding: '6px 16px', borderRadius: '6px', fontSize: '12px', fontWeight: 600,
          cursor: retrying ? 'not-allowed' : 'pointer',
          background: retrying ? '#334155' : '#3b82f6',
          color: '#fff', border: 'none',
          opacity: retrying ? 0.6 : 1,
        }}
      >
        {retrying ? '재시작 중...' : '지금 다시 시도'}
      </button>
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
