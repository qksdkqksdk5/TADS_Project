/* eslint-disable */
// src/modules/monitoring/components/MetricsPanel.jsx
import { useEffect, useRef, useState } from 'react';

// 레벨별 색상·레이블·배경 상수
const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };
const LEVEL_LABEL = { SMOOTH: '원활',    SLOW: '서행',    CONGESTED: '정체',    JAM: '정체'    };
const LEVEL_BG    = { SMOOTH: '#22c55e18', SLOW: '#eab30818', CONGESTED: '#ef444418', JAM: '#ef444418' };

// 예측 레벨별 색상·배경 — 실시간 지표와 동일 팔레트 사용
const PRED_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', JAM: '#ef4444' };
const PRED_LABEL = { SMOOTH: '원활',    SLOW: '서행',    JAM: '정체'    };
const PRED_BG    = { SMOOTH: '#22c55e14', SLOW: '#eab30814', JAM: '#ef444414' };

export default function MetricsPanel({ data }) {
  const prevLevelRef  = useRef(null);
  const [fade,        setFade]        = useState(false);
  const [dirTooltip,  setDirTooltip]  = useState(false);  // 방향 기준 툴팁 표시 여부

  // 레벨 전환 시 fade 애니메이션
  useEffect(() => {
    if (data?.level && prevLevelRef.current && prevLevelRef.current !== data.level) {
      setFade(true);
      const t = setTimeout(() => setFade(false), 500);
      return () => clearTimeout(t);
    }
    if (data?.level) prevLevelRef.current = data.level;
  }, [data?.level]);

  if (!data) {
    return (
      <div style={panelStyle}>
        <div style={headerStyle}>📊 실시간 지표</div>
        <div style={emptyStyle}>구간을 선택하세요</div>
      </div>
    );
  }

  const {
    level,
    dir_label_a, dir_label_b,
    level_a, level_b,
    jam_a, jam_b,
    // dir_a_is_left: A방향 셀의 평균 컬럼이 B보다 작으면 true (A가 화면 왼쪽)
    // 이 값으로 뱃지 좌/우 순서를 결정해 CCTV 영상 속 차선 위치와 일치시킨다.
    dir_a_is_left,
    is_learning, relearning,
    learning_progress, learning_total,
    // HistoricalPredictor가 계산한 5분 후 예측 배열 (없으면 null)
    prediction_a, prediction_b,
  } = data;

  // 화면 왼쪽 뱃지와 오른쪽 뱃지를 dir_a_is_left에 따라 결정한다.
  // dir_a_is_left가 undefined인 경우(학습 전)는 기본값 true(A=왼쪽)를 사용한다.
  const aIsLeft  = dir_a_is_left !== false;
  const leftBadge  = { label: aIsLeft ? (dir_label_a ?? '상행') : (dir_label_b ?? '하행'),
                        level: aIsLeft ? (level_a ?? level)      : (level_b ?? level),
                        jam:   aIsLeft ? (jam_a ?? 0)            : (jam_b ?? 0) };
  const rightBadge = { label: aIsLeft ? (dir_label_b ?? '하행') : (dir_label_a ?? '상행'),
                        level: aIsLeft ? (level_b ?? level)      : (level_a ?? level),
                        jam:   aIsLeft ? (jam_b ?? 0)            : (jam_a ?? 0) };

  const showLearning = is_learning || relearning;
  const progressPct  = learning_total
    ? Math.min(Math.round((learning_progress / learning_total) * 100), 100)
    : 0;

  return (
    <div style={panelStyle}>
      <div style={headerStyle}>📊 실시간 지표</div>

      {/* 방향별 정체 레벨 + 지수 통합 뱃지 ─────────────────────────────
          뱃지 순서는 dir_a_is_left(셀 평균 컬럼 비교)로 결정 →
          CCTV 화면 속 차선 위치와 자동으로 일치한다. */}
      <div style={sectionStyle}>
        <div style={labelStyle}>정체 레벨 · 지수</div>
        {showLearning ? (
          /* 학습 중에는 방향 구분 없이 단일 상태 뱃지 */
          <DirectionBadge
            direction={is_learning ? '학습 중' : '재보정 중'}
            level={null}
            jam={null}
            fade={fade}
          />
        ) : (
          /* 뱃지 영역 — 호버 시 방향 기준 툴팁을 표시한다 */
          <div
            style={{ position: 'relative', display: 'flex', gap: '6px', marginTop: '6px' }}
            onMouseEnter={() => setDirTooltip(true)}
            onMouseLeave={() => setDirTooltip(false)}
          >
            {/* 왼쪽 뱃지 — CCTV 화면 기준 왼쪽 차선 방향 */}
            <DirectionBadge
              direction={leftBadge.label}
              level={leftBadge.level}
              jam={leftBadge.jam}
              fade={fade}
            />
            {/* 오른쪽 뱃지 — CCTV 화면 기준 오른쪽 차선 방향 */}
            <DirectionBadge
              direction={rightBadge.label}
              level={rightBadge.level}
              jam={rightBadge.jam}
              fade={fade}
            />

            {/* 방향 기준 툴팁 — 뱃지 아래로 펼쳐진다
                패널 상단에서 위로 나가면 overflow:hidden에 잘리므로
                top 방향으로 표시하고 꼬리도 위쪽을 가리키도록 한다 */}
            {dirTooltip && (
              <div style={{
                position:      'absolute',
                top:           'calc(100% + 8px)',  // 뱃지 아래 8px
                left:          0,
                right:         0,
                background:    '#1e293b',
                border:        '1px solid #334155',
                borderRadius:  '10px',
                padding:       '12px 12px 10px',
                zIndex:        20,
                boxShadow:     '0 8px 24px #00000088',
                pointerEvents: 'none',
              }}>
                {/* 꼬리 삼각형 — 툴팁 위쪽, 뱃지 중앙을 가리킨다 */}
                <div style={{
                  position:   'absolute',
                  top:        '-5px',
                  left:       '50%',
                  transform:  'translateX(-50%) rotate(45deg)',
                  width:      '8px', height: '8px',
                  background: '#1e293b',
                  borderTop:  '1px solid #334155',
                  borderLeft: '1px solid #334155',
                }} />

                {/* 제목 */}
                <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, marginBottom: '8px', letterSpacing: '0.04em' }}>
                  방향 기준
                  <span style={{ fontSize: '10px', color: '#475569', fontWeight: 400, marginLeft: '5px' }}>CCTV 화면 기준</span>
                </div>

                {/* 상행 행 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', padding: '6px 10px', background: '#0c1628', border: '1px solid #38bdf822', borderRadius: '7px' }}>
                  <span style={{ fontSize: '18px', color: '#38bdf8', lineHeight: 1 }}>↑</span>
                  <div>
                    <div style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 700 }}>상행</div>
                    <div style={{ fontSize: '10px', color: '#64748b', marginTop: '1px' }}>화면 위쪽 방향으로 이동</div>
                  </div>
                </div>

                {/* 하행 행 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', background: '#1a0e06', border: '1px solid #fb923c22', borderRadius: '7px' }}>
                  <span style={{ fontSize: '18px', color: '#fb923c', lineHeight: 1 }}>↓</span>
                  <div>
                    <div style={{ fontSize: '11px', color: '#fb923c', fontWeight: 700 }}>하행</div>
                    <div style={{ fontSize: '10px', color: '#64748b', marginTop: '1px' }}>화면 아래쪽 방향으로 이동</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

      </div>

      {/* 학습 진행 바 */}
      {showLearning && (
        <div style={sectionStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={labelStyle}>{is_learning ? '초기 학습' : '재보정'} 진행</span>
            <span style={{ fontSize: '11px', color: '#64748b' }}>{progressPct}%</span>
          </div>
          <div style={{ background: '#1e293b', borderRadius: '6px', height: '6px', overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${progressPct}%`,
              background: '#38bdf8',
              borderRadius: '6px',
              transition: 'width 0.6s ease',
            }} />
          </div>
          <div style={{ fontSize: '10px', color: '#475569', marginTop: '4px', textAlign: 'right' }}>
            {learning_progress} / {learning_total} 프레임
          </div>
        </div>
      )}

      {/* 정체 예측 영역 — 1h·2h·3h 3열 구조 (132차 개편) */}
      {/* flex: 1 + minHeight: 0 → 남은 공간을 채우되, 부족하면 줄어들어 overflow 방지 */}
      <div style={{ ...sectionStyle, flex: 1, minHeight: 0, borderBottom: 'none', display: 'flex', flexDirection: 'column' }}>
        <div style={labelStyle}>정체 예측 (1h·2h·3h)</div>
        {/* flexDirection: column + minHeight: 0 → 상행/하행 두 행이 가용 공간을 나눠 차지하고 공간 부족 시 함께 축소 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px', flex: 1, minHeight: 0 }}>
          {/* 왼쪽 방향(CCTV 기준) 예측 뱃지 */}
          <PredictionBadge
            direction={leftBadge.label}
            prediction={aIsLeft ? prediction_a : prediction_b}
          />
          {/* 오른쪽 방향(CCTV 기준) 예측 뱃지 */}
          <PredictionBadge
            direction={rightBadge.label}
            prediction={aIsLeft ? prediction_b : prediction_a}
          />
        </div>
      </div>
    </div>
  );
}

// ── 서브 컴포넌트 ────────────────────────────────────────────

// 방향별 정체 레벨·지수 통합 뱃지
// direction: 표시할 방향 레이블 (상행/하행/학습 중 등)
// level:     SMOOTH|SLOW|JAM|null — null이면 회색 처리
// jam:       jam_score 숫자 (0.0~1.0) — 소수점 2자리 표시
function DirectionBadge({ direction, level, jam, fade }) {
  const color = level ? (LEVEL_COLOR[level] || '#6b7280') : '#6b7280';
  const bg    = level ? (LEVEL_BG[level]    || '#37415118') : '#37415118';
  const label = level ? (LEVEL_LABEL[level] || '-') : '-';
  return (
    <div style={{
      flex: 1, padding: '8px', borderRadius: '8px',
      background: bg, border: `1px solid ${color}44`,
      textAlign: 'center',
      transition: 'opacity 0.4s ease', opacity: fade ? 0.2 : 1,
    }}>
      {/* 방향 레이블 */}
      <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '4px' }}>{direction}</div>
      {/* 정체 레벨 텍스트 */}
      <div style={{ fontSize: '14px', fontWeight: 700, color, lineHeight: 1 }}>{label}</div>
      {/* jam_score 수치 — 레벨이 있고 학습 중이 아닌 경우에만 표시 */}
      {jam !== null && (
        <div style={{ fontSize: '11px', color: `${color}cc`, marginTop: '3px' }}>
          {jam.toFixed(2)}
        </div>
      )}
    </div>
  );
}

// 정체 예측 뱃지 — 1h·2h·3h 3열 구조 (132차 개편)
// direction:  표시할 방향 레이블 (상행/하행 등)
// prediction: HistoricalPredictor.predict() 결과 배열 또는 null
//   배열: [{ horizon_min: 60|120|180, predicted_level, confidence, jam_score, interpolated }, ...]
//   null이면 학습 데이터 부족 → "학습 중" 표시
//
// 변경 사항 (132차):
//   - 5분(1개) → 1h·2h·3h 3열 구조로 전면 개편
//   - 헤더에 "1h", "2h", "3h" 시간대 레이블 표시
//   - 데이터 없는 열은 "-" 표시
//   - 신뢰도(%) 표시 제거
function PredictionBadge({ direction, prediction }) {
  // horizon_min → 예측 결과 딕셔너리 (60 → {...}, 120 → {...}, 180 → {...})
  const predByMin = {};
  if (Array.isArray(prediction)) {
    for (const p of prediction) {
      predByMin[p.horizon_min] = p;  // horizon_min 키로 인덱싱
    }
  }
  const hasAny = Object.keys(predByMin).length > 0;  // 데이터가 하나라도 있는지 여부

  // 헤더 시간대 레이블과 대응 horizon_min 목록
  const HORIZONS = [
    { label: '1h', min: 60  },
    { label: '2h', min: 120 },
    { label: '3h', min: 180 },
  ];

  return (
    // flex: 1 + minHeight: 0 → 두 행이 공간을 나눠 차지하되 공간 부족 시 축소 허용
    // 가로 배치: 방향 레이블(왼쪽 고정) + 구분선 + 1h·2h·3h 셀(오른쪽 확장)
    <div style={{
      flex: 1,
      minHeight: 0,
      padding: '8px 10px',
      borderRadius: '8px',
      background: '#0f172a',
      border: '1px solid #1e293b',
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
    }}>
      {/* 방향 레이블 — 왼쪽 고정 너비로 정렬 */}
      <div style={{ fontSize: '10px', color: '#64748b', width: '26px', flexShrink: 0, textAlign: 'center', lineHeight: 1.3 }}>
        {direction}
      </div>

      {/* 세로 구분선 */}
      <div style={{ width: '1px', alignSelf: 'stretch', background: '#1e293b', flexShrink: 0 }} />

      {!hasAny ? (
        /* 데이터 부족 시 학습 중 안내 */
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', color: '#475569' }}>
          학습 중
        </div>
      ) : (
        /* 1h / 2h / 3h 셀 — 가로로 나란히, 세로는 행 높이 가득 채운다 */
        <div style={{ flex: 1, display: 'flex', gap: '4px', alignSelf: 'stretch' }}>
          {HORIZONS.map(({ label, min }) => {
            const p     = predByMin[min] ?? null;  // 해당 horizon 예측 결과 (없으면 null)
            const color = p ? (PRED_COLOR[p.predicted_level] || '#6b7280') : '#475569';
            const bg    = p ? (PRED_BG[p.predicted_level]    || '#37415118') : 'transparent';
            const lv    = p ? (PRED_LABEL[p.predicted_level] || '-') : '-';
            return (
              // 각 셀: 세로 가득 채우고 내용은 중앙 정렬 / overflow:hidden + minHeight:0으로 경계 밖 삐짐 방지
              <div key={min} style={{
                flex: 1,
                minHeight: 0,
                overflow: 'hidden',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                background: bg, border: `1px solid ${color}33`,
                borderRadius: '6px', gap: '2px', padding: '3px 2px',
              }}>
                {/* 시간대 레이블 */}
                <div style={{ fontSize: '9px', color: '#64748b', flexShrink: 0 }}>{label}</div>
                {/* 예측 레벨 — jam_score는 위 뱃지에서 이미 표시하므로 생략 */}
                <div style={{ fontSize: '12px', fontWeight: 700, color, lineHeight: 1, flexShrink: 0 }}>{lv}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── 스타일 상수 ───────────────────────────────────────────────

// overflow: hidden — 예측 영역 내용이 ActionPanel 영역을 침범하지 않도록 한다
// 방향 기준 툴팁은 position:absolute로 MetricsPanel 내부(예측 섹션 위)에 렌더링되므로 클리핑 무관
const panelStyle  = { height: '100%', display: 'flex', flexDirection: 'column', background: '#0f172a', borderRadius: '12px', border: '1px solid #1e293b', overflow: 'hidden' };
const headerStyle = { padding: '10px 14px', borderBottom: '1px solid #1e293b', fontSize: '11px', fontWeight: 700, color: '#64748b', letterSpacing: '0.06em', flexShrink: 0 };
const sectionStyle= { padding: '12px 14px', borderBottom: '1px solid #1e293b', flexShrink: 0 };
const labelStyle  = { fontSize: '11px', color: '#64748b', marginBottom: '6px', display: 'block' };
const emptyStyle  = { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#334155', fontSize: '13px' };
