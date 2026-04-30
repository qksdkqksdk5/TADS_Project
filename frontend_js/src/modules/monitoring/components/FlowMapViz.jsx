/* eslint-disable */
// src/modules/monitoring/components/FlowMapViz.jsx
// 역할: 학습된 플로우맵(flow_map.npy)을 화살표 격자로 시각화하는 모달 컴포넌트
// - 배경: 학습 당시 기준 프레임(ref_frame.jpg)
// - 화살표: 각 격자 셀의 이동 방향 · 세기 · 채널(A/B) 표시
// - 탭: 전체 / A방향(상행) / B방향(하행) 전환 가능

import { useEffect, useRef, useState, useCallback } from 'react';
import { fetchFlowMapViz, swapHist } from '../api';

// ── 색상 상수 ─────────────────────────────────────────────────────────────
const COLOR_A        = '#60a5fa';   // A방향 화살표: 파란색 (상행)
const COLOR_B        = '#fb923c';   // B방향 화살표: 주황색 (하행)
const COLOR_GLOBAL   = '#a78bfa';   // 글로벌 화살표: 보라색 (A+B 혼합)
const COLOR_SMOOTHED = '#94a3b8';   // 보간 채움 셀: 회색 (실 데이터 없음)
const COLOR_ERODED   = '#ef4444';   // 경계 삭제 셀: 빨간 X
const MIN_SAMPLES    = 5;           // 셀 확정 최소 샘플 수 (DetectorConfig와 동일)

// ── 탭 정의 ───────────────────────────────────────────────────────────────
const TABS = [
  { key: 'global', label: '전체(글로벌)' },
  { key: 'a',      label: 'A방향' },
  { key: 'b',      label: 'B방향' },
];

// ══════════════════════════════════════════════════════════════════════════
//  메인 컴포넌트
// ══════════════════════════════════════════════════════════════════════════
export default function FlowMapViz({ host, cameraId, onClose }) {
  const canvasRef    = useRef(null);   // Canvas DOM 참조
  const [vizData,    setVizData]    = useState(null);   // 백엔드 응답 데이터
  const [loading,    setLoading]    = useState(true);   // 로딩 중 여부
  const [error,      setError]      = useState(null);   // 에러 메시지
  const [activeTab,  setActiveTab]  = useState('global'); // 현재 선택된 탭
  const [swapState,  setSwapState]  = useState('idle'); // hist 교환 버튼 상태: idle/loading/done/error

  // ── ESC로 닫기 ────────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // ── hist A↔B 교환 — 플로우맵으로 방향 확인 후 보정 ──────────────────
  const handleSwapHist = async () => {
    if (swapState === 'loading') return;     // 중복 요청 방지
    setSwapState('loading');
    try {
      await swapHist(host, cameraId);        // 백엔드에 교환 요청
      setSwapState('done');
      setTimeout(() => setSwapState('idle'), 4000);  // 4초 후 원래 상태로
    } catch {
      setSwapState('error');
      setTimeout(() => setSwapState('idle'), 3000);  // 3초 후 원래 상태로
    }
  };

  // ── 데이터 fetch ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!cameraId) return;
    setLoading(true);
    setError(null);
    setVizData(null);

    fetchFlowMapViz(host, cameraId)
      .then(res => setVizData(res.data))      // 성공: 데이터 저장
      .catch(err => {
        const msg = err.response?.data?.error || '데이터를 불러올 수 없습니다';
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [host, cameraId]);

  // ── Canvas 그리기 ─────────────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !vizData) return;

    const ctx       = canvas.getContext('2d');
    const W         = canvas.width;
    const H         = canvas.height;
    const gs        = vizData.grid_size;    // 격자 크기 (20 등)
    const cellW     = W / gs;               // 셀 픽셀 너비
    const cellH     = H / gs;              // 셀 픽셀 높이

    // 배경 초기화
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, W, H);

    // ── 배경: 기준 프레임 이미지 ─────────────────────────────────────
    if (vizData.has_ref_frame && vizData.ref_frame_b64) {
      const img = new Image();
      img.onload = () => {
        // 이미지를 Canvas에 맞춰 그린 뒤 격자 화살표를 덧그린다
        ctx.globalAlpha = 0.55;            // 반투명으로 겹쳐 화살표가 잘 보이게
        ctx.drawImage(img, 0, 0, W, H);
        ctx.globalAlpha = 1.0;
        _drawGrid(ctx, vizData, activeTab, W, H, gs, cellW, cellH);
      };
      img.src = vizData.ref_frame_b64;
    } else {
      // 기준 프레임 없으면 바로 격자만 그림
      _drawGrid(ctx, vizData, activeTab, W, H, gs, cellW, cellH);
    }
  }, [vizData, activeTab]);

  // vizData 나 탭이 바뀌면 다시 그림
  useEffect(() => { draw(); }, [draw]);

  // ── 탭 레이블 (A/B는 dir_label 사용) ────────────────────────────────
  const tabLabels = vizData ? [
    { key: 'global', label: '전체(글로벌)' },
    { key: 'a',      label: `A방향 (${vizData.dir_label_a})` },
    { key: 'b',      label: `B방향 (${vizData.dir_label_b})` },
  ] : TABS;

  return (
    /* 모달 오버레이 */
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 2000,
        background: 'rgba(2,6,23,0.88)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* 모달 박스 */}
      <div style={{
        width: 'min(820px, 95vw)',
        background: '#0f172a',
        borderRadius: '16px',
        border: '1px solid #1e293b',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 24px 64px rgba(0,0,0,0.7)',
      }}>

        {/* 헤더 */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '10px 14px', borderBottom: '1px solid #1e293b', flexShrink: 0,
          gap: '12px',
        }}>
          {/* 좌측: 제목 */}
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#e2e8f0', whiteSpace: 'nowrap' }}>
            🗺️ 플로우맵 시각화 — {cameraId}
          </span>

          {/* 우측: hist 교환 버튼 + 닫기 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            {/* 플로우맵으로 방향 확인 후 A/B가 뒤바뀐 경우 보정 */}
            <button
              onClick={handleSwapHist}
              disabled={swapState === 'loading'}
              title="hist_jam_a.csv ↔ hist_jam_b.csv 방향 교환 (A/B 방향이 뒤바뀐 경우 보정)"
              style={{
                padding: '4px 10px', borderRadius: '6px', fontSize: '11px',
                cursor: swapState === 'loading' ? 'not-allowed' : 'pointer',
                background: swapState === 'done'    ? '#14532d22'
                          : swapState === 'error'   ? '#7f1d1d22'
                          : '#1e293b',
                border: `1px solid ${
                          swapState === 'done'    ? '#22c55e44'
                        : swapState === 'error'   ? '#ef444444'
                        : '#334155'}`,
                color:  swapState === 'done'    ? '#22c55e'
                      : swapState === 'error'   ? '#ef4444'
                      : swapState === 'loading' ? '#475569'
                      : '#94a3b8',
                whiteSpace: 'nowrap',
                transition: 'all 0.15s',
              }}
            >
              {swapState === 'loading' ? '교환 중...'
              : swapState === 'done'    ? '✓ 교환 완료'
              : swapState === 'error'   ? '✗ 실패'
              : '⇄ hist 방향 교환'}
            </button>

            {/* 닫기 버튼 */}
            <button
              onClick={onClose}
              style={{
                background: 'transparent', border: '1px solid #1e293b',
                borderRadius: '6px', color: '#475569',
                width: '26px', height: '26px',
                fontSize: '13px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >✕</button>
          </div>
        </div>

        {/* 탭 바 */}
        {!loading && !error && (
          <div style={{
            display: 'flex', gap: '4px',
            padding: '8px 14px 0',
            borderBottom: '1px solid #1e293b',
            flexShrink: 0,
          }}>
            {tabLabels.map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                style={{
                  padding: '5px 12px',
                  borderRadius: '6px 6px 0 0',
                  border: `1px solid ${activeTab === tab.key ? '#3b82f6' : '#1e293b'}`,
                  borderBottom: 'none',
                  background: activeTab === tab.key ? '#1e3a5f' : 'transparent',
                  color: activeTab === tab.key ? '#93c5fd' : '#475569',
                  fontSize: '11px', fontWeight: activeTab === tab.key ? 700 : 400,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* 바디 */}
        <div style={{ padding: '12px', display: 'flex', gap: '12px', minHeight: 0 }}>

          {/* 로딩 */}
          {loading && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', height: '400px' }}>
              <span style={{ fontSize: '13px', color: '#475569' }}>플로우맵 불러오는 중...</span>
            </div>
          )}

          {/* 에러 */}
          {!loading && error && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '400px', gap: '8px' }}>
              <span style={{ fontSize: '20px' }}>⚠️</span>
              <span style={{ fontSize: '13px', color: '#f87171' }}>{error}</span>
              <span style={{ fontSize: '11px', color: '#334155' }}>학습이 완료된 카메라에서만 확인 가능합니다</span>
            </div>
          )}

          {/* Canvas 시각화 */}
          {!loading && !error && vizData && (
            <>
              {/* 캔버스 영역 */}
              <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
                <canvas
                  ref={canvasRef}
                  width={560}
                  height={420}
                  style={{
                    width: '100%', height: 'auto',
                    borderRadius: '8px',
                    border: '1px solid #1e293b',
                    display: 'block',
                  }}
                />
              </div>

              {/* 우측 범례 패널 */}
              <div style={{
                width: '180px', flexShrink: 0,
                display: 'flex', flexDirection: 'column', gap: '8px',
              }}>
                <Legend vizData={vizData} activeTab={activeTab} />
                <Stats vizData={vizData} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  Canvas 그리기 헬퍼 (컴포넌트 외부 순수 함수)
// ══════════════════════════════════════════════════════════════════════════

function _drawGrid(ctx, vizData, activeTab, W, H, gs, cellW, cellH) {
  const { flow, count, flow_a, count_a, flow_b, count_b,
          smoothed_mask, eroded_mask, min_samples } = vizData;

  // 탭에 따라 그릴 flow 배열 / count 배열 / 화살표 색상 결정
  const [drawFlow, drawCount, arrowColor] =
    activeTab === 'a' ? [flow_a, count_a, COLOR_A] :
    activeTab === 'b' ? [flow_b, count_b, COLOR_B] :
                        [flow,   count,   COLOR_GLOBAL];

  for (let r = 0; r < gs; r++) {
    for (let c = 0; c < gs; c++) {
      const cx = (c + 0.5) * cellW;   // 셀 중심 x
      const cy = (r + 0.5) * cellH;   // 셀 중심 y

      // 셀 경계선 (매우 연하게)
      ctx.strokeStyle = 'rgba(100,116,139,0.15)';
      ctx.lineWidth   = 0.5;
      ctx.strokeRect(c * cellW, r * cellH, cellW, cellH);

      // ── eroded(경계 삭제) 셀: 붉은 X ──────────────────────────────
      if (eroded_mask[r][c]) {
        _drawX(ctx, cx, cy, Math.min(cellW, cellH) * 0.25, COLOR_ERODED);
        continue;   // 화살표 건너뜀
      }

      const dx  = drawFlow[r][c][0];   // 방향 벡터 x 성분
      const dy  = drawFlow[r][c][1];   // 방향 벡터 y 성분
      const mag = Math.sqrt(dx * dx + dy * dy);  // 벡터 크기
      if (mag < 0.05) continue;        // 방향 없는 셀 건너뜀

      const cnt       = drawCount[r][c];      // 이 셀의 학습 샘플 수
      const isSmoothed = smoothed_mask[r][c]; // 보간 채움 셀 여부
      const confirmed  = cnt >= min_samples;  // 샘플이 충분해 확정된 셀

      // 화살표 색상 결정: 보간 셀은 회색 / 확정 셀은 채널 색 / 미확정은 반투명
      const color =
        isSmoothed  ? COLOR_SMOOTHED :
        confirmed   ? arrowColor :
                      arrowColor + '66';   // 미확정: 40% 불투명

      // 화살표 길이: 셀 크기의 35% (너무 길면 겹침)
      const arrowLen = Math.min(cellW, cellH) * 0.38;

      _drawArrow(ctx, cx, cy, dx / mag, dy / mag, arrowLen, color, isSmoothed ? 1 : 2);
    }
  }
}

// ── 화살표 그리기 ──────────────────────────────────────────────────────────
function _drawArrow(ctx, cx, cy, ndx, ndy, len, color, lineWidth) {
  const ex = cx + ndx * len;   // 화살표 끝점 x
  const ey = cy + ndy * len;   // 화살표 끝점 y
  const sx = cx - ndx * len * 0.5;   // 화살표 시작점 x (중심에서 절반 뒤)
  const sy = cy - ndy * len * 0.5;   // 화살표 시작점 y

  // 화살표 몸통
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(ex, ey);
  ctx.strokeStyle = color;
  ctx.lineWidth   = lineWidth;
  ctx.stroke();

  // 화살표 머리 (삼각형)
  const headLen   = len * 0.35;      // 머리 길이 (몸통의 35%)
  const headAngle = Math.PI / 6;     // 머리 벌림 각도 30°
  const angle     = Math.atan2(ndy, ndx);  // 이동 방향 각도
  ctx.beginPath();
  ctx.moveTo(ex, ey);
  ctx.lineTo(
    ex - headLen * Math.cos(angle - headAngle),
    ey - headLen * Math.sin(angle - headAngle),
  );
  ctx.moveTo(ex, ey);
  ctx.lineTo(
    ex - headLen * Math.cos(angle + headAngle),
    ey - headLen * Math.sin(angle + headAngle),
  );
  ctx.strokeStyle = color;
  ctx.lineWidth   = lineWidth;
  ctx.stroke();
}

// ── X 표시 그리기 (eroded 셀) ─────────────────────────────────────────────
function _drawX(ctx, cx, cy, r, color) {
  ctx.beginPath();
  ctx.moveTo(cx - r, cy - r);
  ctx.lineTo(cx + r, cy + r);
  ctx.moveTo(cx + r, cy - r);
  ctx.lineTo(cx - r, cy + r);
  ctx.strokeStyle = color;
  ctx.lineWidth   = 1.5;
  ctx.globalAlpha = 0.6;
  ctx.stroke();
  ctx.globalAlpha = 1.0;
}

// ══════════════════════════════════════════════════════════════════════════
//  범례 패널
// ══════════════════════════════════════════════════════════════════════════
function Legend({ vizData, activeTab }) {
  const labelA = vizData?.dir_label_a || 'A방향';
  const labelB = vizData?.dir_label_b || 'B방향';

  return (
    <div style={{
      background: '#0a1628', borderRadius: '8px',
      border: '1px solid #1e293b', padding: '10px',
      display: 'flex', flexDirection: 'column', gap: '6px',
    }}>
      <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748b', marginBottom: '2px', letterSpacing: '0.06em' }}>
        범례
      </div>

      {/* 화살표 종류 */}
      {(activeTab === 'global' || activeTab === 'a') && (
        <LegendRow color={COLOR_A}      label={`A방향 (${labelA}) — 확정`} />
      )}
      {(activeTab === 'global' || activeTab === 'b') && (
        <LegendRow color={COLOR_B}      label={`B방향 (${labelB}) — 확정`} />
      )}
      {activeTab === 'global' && (
        <LegendRow color={COLOR_GLOBAL} label="글로벌 흐름 — 확정" />
      )}
      <LegendRow color={COLOR_SMOOTHED} label="보간 채움 셀 (실측 없음)" dashed />
      <LegendRow color={COLOR_ERODED}   label="경계 삭제 셀" isX />

      <div style={{ borderTop: '1px solid #1e293b', marginTop: '4px', paddingTop: '6px', fontSize: '10px', color: '#334155', lineHeight: 1.6 }}>
        미확정 셀: 반투명 화살표<br/>
        (샘플 {vizData?.min_samples || 5}회 미만)
      </div>
    </div>
  );
}

function LegendRow({ color, label, dashed, isX }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      {isX ? (
        /* X 기호 */
        <span style={{ fontSize: '11px', color, width: '20px', textAlign: 'center', fontWeight: 700 }}>✕</span>
      ) : (
        /* 화살표 선 */
        <svg width="20" height="10">
          <line
            x1="2" y1="5" x2="18" y2="5"
            stroke={color} strokeWidth="2"
            strokeDasharray={dashed ? '3,2' : 'none'}
          />
          <polyline
            points="14,2 18,5 14,8"
            fill="none" stroke={color} strokeWidth="2"
          />
        </svg>
      )}
      <span style={{ fontSize: '10px', color: '#94a3b8', lineHeight: 1.4 }}>{label}</span>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  통계 패널
// ══════════════════════════════════════════════════════════════════════════
function Stats({ vizData }) {
  const { grid_size, min_samples, count, count_a, count_b, smoothed_mask, eroded_mask } = vizData;

  // 셀별 통계 계산
  let totalCells = 0, confirmedCells = 0, smoothedCells = 0, erodedCells = 0;
  let totalSamples = 0, aCells = 0, bCells = 0;

  for (let r = 0; r < grid_size; r++) {
    for (let c = 0; c < grid_size; c++) {
      totalCells++;
      const cnt = count[r][c];
      totalSamples += cnt;
      if (cnt >= min_samples)     confirmedCells++;   // 확정 셀
      if (smoothed_mask[r][c])    smoothedCells++;    // 보간 채움 셀
      if (eroded_mask[r][c])      erodedCells++;      // 경계 삭제 셀
      if (count_a[r][c] > 0)      aCells++;           // A채널 학습 셀
      if (count_b[r][c] > 0)      bCells++;           // B채널 학습 셀
    }
  }

  return (
    <div style={{
      background: '#0a1628', borderRadius: '8px',
      border: '1px solid #1e293b', padding: '10px',
      display: 'flex', flexDirection: 'column', gap: '5px',
    }}>
      <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748b', marginBottom: '2px', letterSpacing: '0.06em' }}>
        학습 현황
      </div>
      <StatRow label="격자 크기"    value={`${grid_size}×${grid_size}`} />
      <StatRow label="총 학습 샘플" value={totalSamples.toLocaleString()} />
      <StatRow label="확정 셀"      value={`${confirmedCells} / ${totalCells}`} color="#22c55e" />
      <StatRow label="A채널 셀"     value={`${aCells}`}   color={COLOR_A} />
      <StatRow label="B채널 셀"     value={`${bCells}`}   color={COLOR_B} />
      <StatRow label="보간 채움 셀" value={`${smoothedCells}`} color={COLOR_SMOOTHED} />
      <StatRow label="경계 삭제 셀" value={`${erodedCells}`}  color={COLOR_ERODED} />
    </div>
  );
}

function StatRow({ label, value, color }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span style={{ fontSize: '10px', color: '#475569' }}>{label}</span>
      <span style={{ fontSize: '11px', fontWeight: 600, color: color || '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </span>
    </div>
  );
}
