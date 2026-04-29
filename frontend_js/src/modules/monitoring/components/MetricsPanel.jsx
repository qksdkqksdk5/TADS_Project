/* eslint-disable */
// src/modules/monitoring/components/MetricsPanel.jsx
// 역할: 선택한 카메라 구간의 실시간 정체 레벨·지수와 1h·2h·3h 예측을 표시하는 패널

// useEffect : 특정 값이 바뀔 때 실행할 코드를 등록 (여기선 레벨 전환 애니메이션)
// useRef    : 화면 갱신 없이 값을 저장 (이전 레벨 기억용)
// useState  : 화면에 반영할 상태 저장 (fade 여부, 툴팁 표시 여부)
import { useEffect, useRef, useState } from 'react';

// ── 레벨별 시각 스타일 상수 ────────────────────────────────────────────────────
// 레벨 → 색상 매핑: 원활=초록, 서행=노랑, 정체(CONGESTED/JAM)=빨강
// CONGESTED와 JAM을 동일 색으로 처리하는 이유: 사용자에게 둘 다 "정체"로 보이게 통일
const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };

// 레벨 → 한국어 레이블: 화면에 표시할 텍스트
const LEVEL_LABEL = { SMOOTH: '원활', SLOW: '서행', CONGESTED: '정체', JAM: '정체' };

// 레벨 → 배경색: 뱃지 배경에 쓰는 반투명 색 (숫자 18 = 16진수 약 9% 불투명도)
const LEVEL_BG = { SMOOTH: '#22c55e18', SLOW: '#eab30818', CONGESTED: '#ef444418', JAM: '#ef444418' };

// ── 예측 레벨별 시각 스타일 상수 ───────────────────────────────────────────────
// 예측(HistoricalPredictor 결과)도 실시간 레벨과 동일한 색상 팔레트 사용
// → 사용자가 실시간과 예측을 같은 기준으로 읽을 수 있도록 일관성 유지
const PRED_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', JAM: '#ef4444' };
const PRED_LABEL = { SMOOTH: '원활',    SLOW: '서행',    JAM: '정체'    };
const PRED_BG    = { SMOOTH: '#22c55e14', SLOW: '#eab30814', JAM: '#ef444414' };
// 14 = 16진수 약 8% 불투명도 — 실시간(18)보다 약간 연하게 표시해 "예측"임을 시각적으로 구분

/**
 * 실시간 정체 지표 + 1h·2h·3h 예측 패널 컴포넌트.
 *
 * 역할:
 *   선택한 카메라 구간의 상행/하행 레벨(SMOOTH/SLOW/JAM)과 jam_score를 뱃지로 표시하고,
 *   HistoricalPredictor가 계산한 1시간·2시간·3시간 뒤 예측 레벨도 함께 보여준다.
 *   학습 중일 때는 레벨 대신 진행 바(progress bar)를 표시한다.
 *
 * @param {object|null} data - 서버에서 받은 카메라 상태 객체 (null이면 "구간을 선택하세요" 표시)
 */
export default function MetricsPanel({ data }) {
  // prevLevelRef: 이전 렌더링의 레벨을 기억 — 현재 레벨과 비교해 전환 여부 판단
  // ref를 쓰는 이유: 레벨 비교용이라 화면 갱신이 필요 없음 (state 불필요)
  const prevLevelRef = useRef(null);

  // fade: true이면 뱃지를 반투명하게 → 레벨이 바뀌는 순간 잠깐 흐릿해지는 애니메이션
  const [fade, setFade] = useState(false);

  // dirTooltip: true이면 방향 기준 툴팁(상행↑ 하행↓ 설명)을 표시
  // 뱃지 영역에 마우스를 올리면 true, 벗어나면 false
  const [dirTooltip, setDirTooltip] = useState(false);

  // ── 레벨 전환 시 fade 애니메이션 ─────────────────────────────────────────────
  // data.level이 바뀔 때마다 실행된다
  useEffect(() => {
    // 이전 레벨이 있고 현재 레벨과 다르면 (= 레벨이 전환된 순간)
    if (data?.level && prevLevelRef.current && prevLevelRef.current !== data.level) {
      setFade(true);                              // 뱃지를 반투명하게 (CSS transition으로 서서히)
      const t = setTimeout(() => setFade(false), 500); // 500ms 후 다시 선명하게 복구
      return () => clearTimeout(t);               // 컴포넌트 unmount나 level 재변경 시 타이머 정리
    }
    // 현재 레벨을 기억해뒀다가 다음 렌더링에서 비교
    if (data?.level) prevLevelRef.current = data.level;
  }, [data?.level]); // data.level이 바뀔 때만 실행

  // ── data가 없으면 빈 상태 표시 ───────────────────────────────────────────────
  // 구간을 아직 선택하지 않았거나 카메라 데이터가 없는 경우
  if (!data) {
    return (
      <div style={panelStyle}>
        <div style={headerStyle}>📊 실시간 지표</div>
        <div style={emptyStyle}>구간을 선택하세요</div>
      </div>
    );
  }

  // ── data에서 필요한 값 꺼내기 ────────────────────────────────────────────────
  const {
    level,                      // 전체 구간 레벨 (SMOOTH/SLOW/JAM)
    dir_label_a, dir_label_b,   // 방향 레이블 (예: '상행', '하행')
    level_a, level_b,           // A방향·B방향 레벨
    jam_a, jam_b,               // A방향·B방향 jam_score (0.0~1.0)
    // dir_a_is_left: A방향 셀의 평균 컬럼이 B보다 작으면 true → A가 화면 왼쪽 차선
    // 이 값으로 뱃지 좌/우 순서를 결정해 CCTV 영상 속 차선 위치와 일치시킨다
    dir_a_is_left,
    is_learning,                // 초기 학습 중 여부 (true면 레벨 대신 진행 바 표시)
    relearning,                 // 재보정 학습 중 여부
    learning_progress,          // 현재 학습 완료 프레임 수
    learning_total,             // 전체 학습 목표 프레임 수
    // prediction_a/b: HistoricalPredictor가 계산한 1h·2h·3h 예측 배열
    // 형식: [{ horizon_min: 60|120|180, predicted_level, confidence, jam_score }, ...]
    // null이면 학습 데이터 부족 → "학습 중" 표시
    prediction_a, prediction_b,
  } = data;

  // ── 뱃지 좌우 배치 결정 ──────────────────────────────────────────────────────
  // dir_a_is_left가 undefined인 경우(학습 전 데이터 없음)는 기본값 true(A=왼쪽)로 처리
  const aIsLeft = dir_a_is_left !== false; // false가 아닌 모든 값(true, undefined)은 A=왼쪽

  // 왼쪽 뱃지: A가 왼쪽이면 A방향 데이터, 아니면 B방향 데이터 사용
  const leftBadge = {
    label: aIsLeft ? (dir_label_a ?? '상행') : (dir_label_b ?? '하행'), // 방향 레이블
    level: aIsLeft ? (level_a ?? level)      : (level_b ?? level),      // 레벨 (없으면 전체 레벨로 폴백)
    jam:   aIsLeft ? (jam_a ?? 0)            : (jam_b ?? 0),            // jam_score
  };

  // 오른쪽 뱃지: 왼쪽과 반대 방향 데이터 사용
  const rightBadge = {
    label: aIsLeft ? (dir_label_b ?? '하행') : (dir_label_a ?? '상행'),
    level: aIsLeft ? (level_b ?? level)      : (level_a ?? level),
    jam:   aIsLeft ? (jam_b ?? 0)            : (jam_a ?? 0),
  };

  // ── 학습 진행률 계산 ─────────────────────────────────────────────────────────
  // showLearning: 초기 학습 또는 재보정 중일 때 true → 진행 바를 표시한다
  const showLearning = is_learning || relearning;

  // progressPct: 0~100 정수 (진행 바 너비에 사용)
  // learning_total이 0이면 나누기 오류 방지를 위해 0으로 처리
  const progressPct = learning_total
    ? Math.min(Math.round((learning_progress / learning_total) * 100), 100)
    : 0;

  return (
    <div style={panelStyle}>
      {/* 패널 헤더 */}
      <div style={headerStyle}>📊 실시간 지표</div>

      {/* ── 방향별 정체 레벨 + 지수 뱃지 영역 ─────────────────────────────────
          뱃지 순서는 dir_a_is_left로 결정 → CCTV 화면 속 차선 위치와 자동으로 일치 */}
      <div style={sectionStyle}>
        <div style={labelStyle}>정체 레벨 · 지수</div>

        {showLearning ? (
          /* 학습 중에는 방향 구분 없이 단일 상태 뱃지 표시 */
          <DirectionBadge
            direction={is_learning ? '학습 중' : '재보정 중'} // 초기 학습이면 '학습 중', 재보정이면 '재보정 중'
            level={null}   // 학습 중에는 레벨 없음 → 회색으로 표시
            jam={null}     // jam_score도 표시 안 함
            fade={fade}    // 레벨 전환 애니메이션 (학습 중에는 사실상 무효)
          />
        ) : (
          /* 학습 완료 시: 왼쪽·오른쪽 방향 뱃지 2개 표시
             마우스를 올리면 방향 기준(상행↑ 하행↓) 툴팁이 나타난다 */
          <div
            style={{ position: 'relative', display: 'flex', gap: '6px', marginTop: '6px' }}
            onMouseEnter={() => setDirTooltip(true)}  // 뱃지 영역에 마우스 진입 → 툴팁 표시
            onMouseLeave={() => setDirTooltip(false)} // 뱃지 영역 벗어남 → 툴팁 숨김
          >
            {/* 왼쪽 뱃지 — CCTV 화면 기준 왼쪽 차선 방향 */}
            <DirectionBadge
              direction={leftBadge.label}  // 방향 레이블 (예: '상행')
              level={leftBadge.level}      // 레벨 (SMOOTH/SLOW/JAM)
              jam={leftBadge.jam}          // jam_score 숫자
              fade={fade}                  // 레벨 전환 시 fade 애니메이션 적용
            />
            {/* 오른쪽 뱃지 — CCTV 화면 기준 오른쪽 차선 방향 */}
            <DirectionBadge
              direction={rightBadge.label}
              level={rightBadge.level}
              jam={rightBadge.jam}
              fade={fade}
            />

            {/* 방향 기준 툴팁 — 뱃지 아래로 펼쳐진다
                position:absolute 라서 부모(position:relative) 기준으로 위치 잡힘
                패널 상단 overflow:hidden에 잘리지 않도록 top(아래쪽) 방향으로 표시 */}
            {dirTooltip && (
              <div style={{
                position:      'absolute',
                top:           'calc(100% + 8px)', // 뱃지 바로 아래 8px
                left:          0,
                right:         0,
                background:    '#1e293b',          // 어두운 배경
                border:        '1px solid #334155',
                borderRadius:  '10px',
                padding:       '12px 12px 10px',
                zIndex:        20,                 // 다른 요소 위에 표시
                boxShadow:     '0 8px 24px #00000088',
                pointerEvents: 'none',             // 툴팁 자체는 마우스 이벤트를 받지 않음 (hover 유지)
              }}>
                {/* 꼬리 삼각형 — 툴팁 위쪽에서 뱃지 중앙을 가리키는 화살표 효과 */}
                <div style={{
                  position:   'absolute',
                  top:        '-5px',              // 툴팁 테두리 위로 살짝 올라감
                  left:       '50%',
                  transform:  'translateX(-50%) rotate(45deg)', // 45° 회전으로 삼각형 효과
                  width:      '8px', height: '8px',
                  background: '#1e293b',
                  borderTop:  '1px solid #334155', // 테두리 위쪽만 표시 (꼬리 모양)
                  borderLeft: '1px solid #334155', // 테두리 왼쪽만 표시
                }} />

                {/* 툴팁 제목 */}
                <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, marginBottom: '8px', letterSpacing: '0.04em' }}>
                  방향 기준
                  <span style={{ fontSize: '10px', color: '#475569', fontWeight: 400, marginLeft: '5px' }}>CCTV 화면 기준</span>
                </div>

                {/* 상행 설명 행 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', padding: '6px 10px', background: '#0c1628', border: '1px solid #38bdf822', borderRadius: '7px' }}>
                  <span style={{ fontSize: '18px', color: '#38bdf8', lineHeight: 1 }}>↑</span>
                  <div>
                    <div style={{ fontSize: '11px', color: '#38bdf8', fontWeight: 700 }}>상행</div>
                    <div style={{ fontSize: '10px', color: '#64748b', marginTop: '1px' }}>화면 위쪽 방향으로 이동</div>
                  </div>
                </div>

                {/* 하행 설명 행 */}
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

      {/* ── 학습 진행 바 — 학습/재보정 중일 때만 표시 ───────────────────────── */}
      {showLearning && (
        <div style={sectionStyle}>
          {/* 상단: 학습 종류 레이블 + 퍼센트 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={labelStyle}>{is_learning ? '초기 학습' : '재보정'} 진행</span>
            <span style={{ fontSize: '11px', color: '#64748b' }}>{progressPct}%</span>
          </div>
          {/* 진행 바 외곽 */}
          <div style={{ background: '#1e293b', borderRadius: '6px', height: '6px', overflow: 'hidden' }}>
            {/* 진행 바 내부 — width를 progressPct%로 설정, CSS transition으로 부드럽게 늘어남 */}
            <div style={{
              height:     '100%',
              width:      `${progressPct}%`,      // 현재 진행률만큼 너비 설정
              background: '#38bdf8',              // 파란색 진행 바
              borderRadius: '6px',
              transition: 'width 0.6s ease',      // 0.6초에 걸쳐 부드럽게 늘어남
            }} />
          </div>
          {/* 하단: 현재 프레임 수 / 전체 프레임 수 */}
          <div style={{ fontSize: '10px', color: '#475569', marginTop: '4px', textAlign: 'right' }}>
            {learning_progress} / {learning_total} 프레임
          </div>
        </div>
      )}

      {/* ── 정체 예측 영역 — 1h·2h·3h 3열 구조 ─────────────────────────────────
          flex: 1 + minHeight: 0 → 패널에서 남은 공간을 채우되, 부족하면 줄어들어 overflow 방지 */}
      <div style={{ ...sectionStyle, flex: 1, minHeight: 0, borderBottom: 'none', display: 'flex', flexDirection: 'column' }}>
        <div style={labelStyle}>정체 예측 (1h·2h·3h)</div>

        {/* 상행·하행 두 행이 가용 공간을 나눠 차지하고, 공간 부족 시 함께 축소 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px', flex: 1, minHeight: 0 }}>
          {/* 왼쪽 방향 예측 — CCTV 화면 기준 왼쪽 차선 */}
          <PredictionBadge
            direction={leftBadge.label}                      // 방향 레이블
            prediction={aIsLeft ? prediction_a : prediction_b} // A가 왼쪽이면 A예측, 아니면 B예측
          />
          {/* 오른쪽 방향 예측 — CCTV 화면 기준 오른쪽 차선 */}
          <PredictionBadge
            direction={rightBadge.label}
            prediction={aIsLeft ? prediction_b : prediction_a}
          />
        </div>
      </div>
    </div>
  );
}

// ── 서브 컴포넌트: DirectionBadge ────────────────────────────────────────────
/**
 * 방향별 정체 레벨과 jam_score를 한 눈에 보여주는 뱃지.
 *
 * @param {string}      direction - 표시할 방향 레이블 (예: '상행', '하행', '학습 중')
 * @param {string|null} level     - SMOOTH|SLOW|JAM|null (null이면 회색 처리)
 * @param {number|null} jam       - jam_score (0.0~1.0), null이면 숫자 표시 안 함
 * @param {boolean}     fade      - true이면 반투명 (레벨 전환 애니메이션)
 */
function DirectionBadge({ direction, level, jam, fade }) {
  // level이 없으면 회색 계열로, 있으면 레벨에 맞는 색으로 표시
  const color = level ? (LEVEL_COLOR[level] || '#6b7280') : '#6b7280'; // 알 수 없는 레벨은 회색
  const bg    = level ? (LEVEL_BG[level]    || '#37415118') : '#37415118'; // 배경도 레벨 색 기반
  const label = level ? (LEVEL_LABEL[level] || '-') : '-';               // 한국어 레벨 텍스트

  return (
    <div style={{
      flex:       1,             // 두 뱃지가 가로 공간을 반반 나눔
      padding:    '8px',
      borderRadius: '8px',
      background: bg,
      border:     `1px solid ${color}44`, // 레벨 색의 약 27% 불투명도 테두리
      textAlign:  'center',
      transition: 'opacity 0.4s ease',   // 0.4초에 걸쳐 투명도 변화 (fade 효과)
      opacity:    fade ? 0.2 : 1,        // fade=true이면 반투명 (레벨 전환 순간)
    }}>
      {/* 방향 레이블 — 회색 소문자로 위에 표시 */}
      <div style={{ fontSize: '10px', color: '#64748b', marginBottom: '4px' }}>{direction}</div>

      {/* 정체 레벨 텍스트 — 굵고 크게 */}
      <div style={{ fontSize: '14px', fontWeight: 700, color, lineHeight: 1 }}>{label}</div>

      {/* jam_score 수치 — level이 있고(학습 완료) jam이 null이 아닐 때만 표시 */}
      {jam !== null && (
        <div style={{ fontSize: '11px', color: `${color}cc`, marginTop: '3px' }}>
          {jam.toFixed(2)} {/* 소수점 2자리로 표시 (예: 0.73) */}
        </div>
      )}
    </div>
  );
}

// ── 서브 컴포넌트: PredictionBadge ───────────────────────────────────────────
/**
 * 1시간·2시간·3시간 뒤 예측 레벨을 3열로 표시하는 뱃지.
 *
 * @param {string}      direction  - 표시할 방향 레이블 (예: '상행')
 * @param {Array|null}  prediction - HistoricalPredictor.predict() 결과 배열 또는 null
 *   배열 형식: [{ horizon_min: 60|120|180, predicted_level, confidence, jam_score }, ...]
 *   null이면 학습 데이터 부족 → "학습 중" 표시
 */
function PredictionBadge({ direction, prediction }) {
  // prediction 배열을 horizon_min(60/120/180) 키로 인덱싱 — 빠른 조회를 위해 객체로 변환
  const predByMin = {};
  if (Array.isArray(prediction)) {
    for (const p of prediction) {
      predByMin[p.horizon_min] = p; // 예: { 60: {...}, 120: {...}, 180: {...} }
    }
  }

  // 데이터가 하나라도 있으면 예측 표시, 없으면 "학습 중" 표시
  const hasAny = Object.keys(predByMin).length > 0;

  // 표시할 시간대 목록 — 1h(60분), 2h(120분), 3h(180분)
  const HORIZONS = [
    { label: '1h', min: 60  },
    { label: '2h', min: 120 },
    { label: '3h', min: 180 },
  ];

  return (
    // 가로 배치: 방향 레이블(왼쪽 고정) + 세로 구분선 + 1h·2h·3h 셀(오른쪽 확장)
    // flex: 1 + minHeight: 0 → 두 행이 공간을 나눠 차지하되, 공간 부족 시 축소 허용
    <div style={{
      flex:        1,
      minHeight:   0,
      padding:     '8px 10px',
      borderRadius: '8px',
      background:  '#0f172a',       // 어두운 배경 (패널 배경보다 약간 밝음)
      border:      '1px solid #1e293b',
      display:     'flex',
      alignItems:  'center',
      gap:         '8px',
    }}>
      {/* 방향 레이블 — 왼쪽 고정 너비로 1h·2h·3h 셀과 정렬 */}
      <div style={{ fontSize: '10px', color: '#64748b', width: '26px', flexShrink: 0, textAlign: 'center', lineHeight: 1.3 }}>
        {direction}
      </div>

      {/* 세로 구분선 — 방향 레이블과 예측 셀 사이 시각적 분리 */}
      <div style={{ width: '1px', alignSelf: 'stretch', background: '#1e293b', flexShrink: 0 }} />

      {!hasAny ? (
        /* 학습 데이터 부족: 예측 불가 → "학습 중" 안내 */
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', color: '#475569' }}>
          학습 중
        </div>
      ) : (
        /* 1h / 2h / 3h 예측 셀 — 가로로 나란히, 세로는 행 높이 가득 채움 */
        <div style={{ flex: 1, display: 'flex', gap: '4px', alignSelf: 'stretch' }}>
          {HORIZONS.map(({ label, min }) => {
            const p     = predByMin[min] ?? null;  // 해당 시간대 예측 결과 (없으면 null)
            const color = p ? (PRED_COLOR[p.predicted_level] || '#6b7280') : '#475569'; // 예측 레벨 색
            const bg    = p ? (PRED_BG[p.predicted_level]    || '#37415118') : 'transparent'; // 배경색
            const lv    = p ? (PRED_LABEL[p.predicted_level] || '-') : '-';               // 한국어 레벨

            return (
              // 각 셀: flex 1로 가로 공간 균등 분배, overflow:hidden으로 경계 밖 삐짐 방지
              <div key={min} style={{
                flex:         1,
                minHeight:    0,
                overflow:     'hidden',
                display:      'flex', flexDirection: 'column',
                alignItems:   'center', justifyContent: 'center',
                background:   bg,
                border:       `1px solid ${color}33`, // 예측 레벨 색의 약 20% 불투명도 테두리
                borderRadius: '6px',
                gap:          '2px',
                padding:      '3px 2px',
              }}>
                {/* 시간대 레이블 (1h / 2h / 3h) */}
                <div style={{ fontSize: '9px', color: '#64748b', flexShrink: 0 }}>{label}</div>
                {/* 예측 레벨 텍스트 */}
                <div style={{ fontSize: '12px', fontWeight: 700, color, lineHeight: 1, flexShrink: 0 }}>{lv}</div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── 스타일 상수 ───────────────────────────────────────────────────────────────
// overflow: hidden — 예측 영역 내용이 ActionPanel 영역을 침범하지 않도록 한다
// (방향 기준 툴팁은 position:absolute라 overflow:hidden에 잘리지 않음)
const panelStyle = {
  height:        '100%',
  display:       'flex',
  flexDirection: 'column',
  background:    '#0f172a',     // 패널 배경 — 가장 어두운 계열
  borderRadius:  '12px',
  border:        '1px solid #1e293b',
  overflow:      'hidden',      // 자식 요소가 패널 경계 밖으로 나가지 않도록
};

const headerStyle = {
  padding:       '10px 14px',
  borderBottom:  '1px solid #1e293b',
  fontSize:      '11px',
  fontWeight:    700,
  color:         '#64748b',
  letterSpacing: '0.06em',
  flexShrink:    0,             // 헤더는 패널이 좁아져도 줄어들지 않음
};

const sectionStyle = {
  padding:      '12px 14px',
  borderBottom: '1px solid #1e293b',
  flexShrink:   0,              // 섹션도 줄어들지 않음 — 예측 영역(flex:1)이 남은 공간 차지
};

const labelStyle = {
  fontSize:    '11px',
  color:       '#64748b',
  marginBottom: '6px',
  display:     'block',         // 블록 요소로 줄 차지
};

const emptyStyle = {
  flex:           1,            // 남은 공간 전체 차지
  display:        'flex',
  alignItems:     'center',
  justifyContent: 'center',
  color:          '#334155',
  fontSize:       '13px',
};
