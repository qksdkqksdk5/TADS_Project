/* eslint-disable */
// src/modules/monitoring/components/SectionList.jsx
// 고속도로 탭 선택 → 시작/종료 IC 지정 → 구간 모니터링 시작/중지 + 카메라 목록 표시
import { useState, useEffect, useCallback, useMemo } from 'react'; // 필요한 React 훅 임포트
import { fetchItsCctv, startSegment, stopSegment } from '../api';   // 서버 API 호출 함수 임포트

// 정체 레벨별 색상 — CONGESTED와 JAM은 동일하게 빨간색으로 처리한다
const LEVEL_COLOR = { SMOOTH: '#22c55e', SLOW: '#eab308', CONGESTED: '#ef4444', JAM: '#ef4444' };

// 정체 레벨별 한국어 표시 레이블 — UI에 영어 코드 대신 친숙한 단어로 보여준다
const LEVEL_LABEL = { SMOOTH: '원활', SLOW: '서행', CONGESTED: '정체', JAM: '정체' };

// 지원하는 고속도로 목록 — key 는 API 파라미터, label 은 화면 탭에 표시할 텍스트
// 새로운 고속도로 추가 시 이 배열에만 항목을 추가하면 탭과 API 호출이 자동으로 처리된다
const ROADS = [
  { key: 'gyeongbu',  label: '경부' },   // 경부고속도로
  { key: 'gyeongin',  label: '경인' },   // 경인고속도로
  { key: 'seohae',    label: '서해안' }, // 서해안고속도로
  { key: 'youngdong', label: '영동' },   // 영동고속도로
  { key: 'jungang',   label: '중앙' },   // 중앙고속도로
];

// ── 메인 컴포넌트 ─────────────────────────────────────────────────────────────
// Props:
//   host             — 백엔드 서버 주소 (예: "localhost:5000")
//   cameras          — 현재 모니터링 중인 카메라 객체 맵 { camera_id: cameraData }
//   selectedId       — 현재 선택된 카메라 ID (선택된 카메라에 강조 테두리 표시)
//   onSelect         — 카메라 클릭 시 부모에게 선택 ID를 전달하는 콜백
//   onViewItsCctv    — ITS CCTV "보기" 버튼 클릭 시 부모에게 카메라 정보를 전달하는 콜백
//   onCctvListChange — ITS CCTV 목록이 새로 로드됐을 때 부모(지도 마커 업데이트)에게 전달하는 콜백
//   onRemoveCameras  — 구간 중지 후 중지된 카메라 ID 배열을 부모에게 전달하는 콜백
//   onRoadChange     — 도로 탭 변경 시 새 road 키를 부모에게 전달하는 콜백 (지도 오버레이 교체용)
export default function SectionList({ host, cameras, selectedId, onSelect, onViewItsCctv, onCctvListChange, onRemoveCameras, onRoadChange }) {
  // road: 현재 선택된 고속도로 키 (기본값: 경부)
  const [road,        setRoad]        = useState('gyeongbu');
  // cctvList: 현재 선택된 고속도로의 ITS CCTV 전체 목록
  const [cctvList,    setCctvList]    = useState([]);
  // icList: 현재 고속도로의 IC(인터체인지) 이름 배열 — 드롭다운 옵션으로 사용
  const [icList,      setIcList]      = useState([]);
  // startIC / endIC: 구간 모니터링 시작/종료 지점 선택값
  const [startIC,     setStartIC]     = useState('');
  const [endIC,       setEndIC]       = useState('');
  // loadingCctv: CCTV 목록 로딩 중 여부 — 로딩 중에는 스피너 메시지를 보여준다
  const [loadingCctv, setLoadingCctv] = useState(false);
  // loadingSeg: 구간 시작/중지 처리 중 여부 — 버튼을 비활성화해 중복 클릭 방지
  const [loadingSeg,  setLoadingSeg]  = useState(false);
  // segError: 구간 시작/중지 결과 메시지 (성공 또는 실패 문자열)
  const [segError,    setSegError]    = useState('');
  // showAllCctv: ITS CCTV 전체 목록 펼치기/접기 토글 상태
  const [showAllCctv, setShowAllCctv] = useState(false);

  // 고속도로 탭이 바뀌거나 host 가 설정될 때마다 CCTV 목록을 서버에서 새로 가져온다
  useEffect(() => {
    if (!host) return; // host 가 없으면(서버 주소 미설정) 요청하지 않는다
    setLoadingCctv(true); // 로딩 시작 표시
    setCctvList([]);       // 이전 도로의 목록 초기화
    setIcList([]);         // IC 목록도 초기화
    setStartIC('');        // 시작 IC 선택 초기화
    setEndIC('');          // 종료 IC 선택 초기화
    setSegError('');       // 에러 메시지 초기화

    fetchItsCctv(host, road) // 선택된 도로의 ITS CCTV 목록 요청
      .then(res => {
        const cameras_data = res.data.cameras || []; // 카메라 목록 추출 (없으면 빈 배열)
        setCctvList(cameras_data);                    // CCTV 목록 상태 저장
        setIcList(res.data.ic_list || []);            // IC 목록 상태 저장
        onCctvListChange?.(cameras_data);             // 부모(지도)에게 ITS 마커 목록 전달
      })
      .catch(() => setSegError('CCTV 목록 로드 실패')) // 요청 실패 시 에러 메시지 표시
      .finally(() => setLoadingCctv(false));           // 성공/실패 모두 로딩 상태 해제
  }, [road, host]); // road 또는 host 가 바뀔 때마다 재실행

  // 도로 탭이 바뀔 때 부모(index.jsx)에게 새 road 키를 알려주어 지도 오버레이도 교체하게 한다
  useEffect(() => {
    onRoadChange?.(road); // onRoadChange 콜백이 있을 때만 호출 (없으면 무시)
  }, [road]); // road 가 바뀔 때마다 실행

  // IC 목록이 로드된 후 시작/종료 IC의 기본값을 첫 번째 IC로 설정한다
  // ⚠️ 기본값을 마지막 IC로 설정하면 endOptions 목록이 서초(첫 번째)부터 시작하는데
  //    선택값이 맨 끝이라 드롭다운을 열었을 때 맨 아래가 보이는 UX 버그가 발생했다.
  //    첫 번째 IC로 통일하면 드롭다운이 항상 맨 위에서 열린다.
  useEffect(() => {
    if (icList.length >= 2) {
      setStartIC(prev => prev || icList[0]); // 이미 값이 있으면 바꾸지 않고, 없으면 첫 번째로 설정
      setEndIC(prev   => prev || icList[0]); // 종료 IC도 동일하게 첫 번째로 설정
    }
  }, [icList]); // icList 가 바뀔 때(도로 탭 전환 후 새 목록 도착)만 실행

  // 종료 IC 드롭다운 옵션 — startIC 위치부터 시작하도록 icList를 "회전"해서 만든다
  // 예) icList=['서초','양재','원지동','상적교'], startIC='양재'
  //     → ['양재','원지동','상적교','서초']
  // 이유: 시작 IC를 '양재'로 고르면 종료 IC는 '양재' 이후 구간만 의미있다.
  //       회전하지 않으면 종료 드롭다운이 항상 '서초'부터 시작해서 방향이 뒤바뀐다.
  const endOptions = useMemo(() => {
    if (!startIC) return [...icList];           // startIC 미선택 시 원본 순서 그대로 반환
    const idx = icList.indexOf(startIC);        // icList에서 startIC 가 몇 번째인지 탐색
    if (idx <= 0) return [...icList];           // 이미 첫 번째이거나 못 찾으면 그대로 반환
    // startIC 위치부터 자르고 앞 부분을 뒤에 이어 붙여 회전 효과를 만든다
    return [...icList.slice(idx), ...icList.slice(0, idx)];
  }, [icList, startIC]); // icList 또는 startIC 가 바뀔 때만 재계산 (useMemo로 불필요한 재계산 방지)

  // 구간 시작 버튼 핸들러 — 선택된 구간의 CCTV를 일괄 모니터링 시작한다
  const handleStartSegment = useCallback(async () => {
    if (!startIC || !endIC) { setSegError('시작/종료 IC를 선택하세요'); return; } // 미선택 시 에러 표시
    setLoadingSeg(true); // 버튼 비활성화 (처리 중 표시)
    setSegError('');      // 이전 메시지 초기화
    try {
      const res = await startSegment(host, road, startIC, endIC); // 서버에 구간 시작 요청
      const d   = res.data;
      setSegError(d.message || '완료'); // 서버 응답 메시지 표시
    } catch (e) {
      // 서버가 에러 응답을 보낸 경우 메시지 추출, 없으면 기본 에러 메시지 사용
      const msg = e?.response?.data?.message || '구간 시작 실패 — 서버 확인';
      setSegError(msg);
    } finally {
      setLoadingSeg(false); // 성공/실패 모두 버튼 다시 활성화
    }
  }, [host, road, startIC, endIC]); // 이 값들이 바뀌면 핸들러를 새로 만든다

  // 구간 중지 버튼 핸들러 — 선택된 구간의 CCTV를 일괄 모니터링 중지한다
  const handleStopSegment = useCallback(async () => {
    if (!startIC || !endIC) return; // IC 미선택 시 아무것도 하지 않음
    setLoadingSeg(true); // 버튼 비활성화
    setSegError('');      // 이전 메시지 초기화
    try {
      const res = await stopSegment(host, road, startIC, endIC);  // 서버에 구간 중지 요청
      const stopped = res.data.stopped || []; // 실제로 중지된 카메라 ID 배열
      if (stopped.length > 0) {
        onRemoveCameras?.(stopped); // 부모(index.jsx)에게 제거할 카메라 목록 전달
      }
      // 중지된 카메라 수를 결과 메시지로 표시한다
      setSegError(stopped.length > 0 ? `${stopped.length}개 중지 완료` : '중지할 카메라 없음');
    } catch {
      setSegError('구간 중지 실패'); // 서버 오류 시 에러 메시지 표시
    } finally {
      setLoadingSeg(false); // 버튼 다시 활성화
    }
  }, [host, road, startIC, endIC, onRemoveCameras]); // 의존값 변경 시 핸들러 재생성

  // 현재 모니터링 중인 카메라 목록 — cameras 객체를 배열로 변환하고 심각도 순으로 정렬
  // 정렬 기준: JAM/CONGESTED(0) → SLOW(1) → SMOOTH(2) — 심각한 상황이 위에 오도록
  // 이유: 운영자가 목록을 열었을 때 즉시 가장 위험한 상황을 볼 수 있어야 하기 때문
  const monitoringList = Object.values(cameras).sort((a, b) => {
    const order = { CONGESTED: 0, JAM: 0, SLOW: 1, SMOOTH: 2 }; // 정렬 우선순위 맵
    return (order[a.level] ?? 3) - (order[b.level] ?? 3);        // 낮은 숫자가 앞으로
  });

  return (
    // height:100% + flex column: 헤더/탭을 상단에 고정하고 나머지 영역만 스크롤되게 한다
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── 헤더 ─────────────────────────────────────────────────── */}
      <div style={styles.header}>📍 구간 목록</div>

      {/* ── 고속도로 탭 — ROADS 배열을 순회해 탭 버튼을 동적으로 생성한다 ── */}
      <div style={styles.tabRow}>
        {ROADS.map(r => (
          <button
            key={r.key}                         // React가 각 버튼을 구분하기 위한 고유 키
            onClick={() => setRoad(r.key)}       // 탭 클릭 시 선택 도로 변경
            style={{
              ...styles.tab,
              // 선택된 탭은 배경·색상·하단 밑줄로 구분한다
              background:   road === r.key ? '#1e3a5f'      : 'transparent',
              color:        road === r.key ? '#93c5fd'      : '#475569',
              borderBottom: road === r.key ? '2px solid #3b82f6' : '2px solid transparent',
            }}
          >
            {r.label} {/* "경부", "경인" 등 한국어 탭 레이블 */}
          </button>
        ))}
      </div>

      {/* ── 스크롤 가능한 콘텐츠 영역 ────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto' }}>

        {/* ── 구간 모니터링 설정 박스 ──────────────────────────── */}
        <div style={styles.segBox}>
          <div style={styles.segLabel}>구간 모니터링</div>

          {/* CCTV 목록 로딩 중에는 드롭다운 대신 안내 텍스트를 표시한다 */}
          {loadingCctv ? (
            <div style={styles.dimText}>CCTV 목록 로딩 중...</div>
          ) : (
            <>
              {/* 시작/종료 IC 드롭다운 — 나란히 배치 */}
              <div style={{ display: 'flex', gap: '4px', marginBottom: '5px' }}>
                <IcSelect
                  label="시작"
                  value={startIC}
                  options={icList}          // 시작 IC는 원본 순서 그대로
                  onChange={(val) => {
                    setStartIC(val);        // 시작 IC 변경
                    setEndIC(val);          // 종료 IC도 같은 값으로 리셋 → 드롭다운이 맨 위에서 열림
                  }}
                />
                <IcSelect
                  label="종료"
                  value={endIC}
                  options={endOptions}      // 종료 IC는 startIC 위치부터 회전된 목록
                  onChange={setEndIC}       // 종료 IC만 변경 (시작 IC에는 영향 없음)
                />
              </div>

              {/* 시작/중지 버튼 — 시작은 강조색, 중지는 회색으로 구분 */}
              <div style={{ display: 'flex', gap: '4px' }}>
                <button
                  onClick={handleStartSegment}
                  disabled={loadingSeg}    // 처리 중에는 버튼 비활성화
                  style={{ ...styles.btn, flex: 2, background: '#1e3a5f', color: '#93c5fd', border: '1px solid #2563eb44' }}
                >
                  {loadingSeg ? '처리 중...' : '▶ 시작'} {/* 처리 중 텍스트로 피드백 */}
                </button>
                <button
                  onClick={handleStopSegment}
                  disabled={loadingSeg}    // 처리 중에는 버튼 비활성화
                  style={{ ...styles.btn, flex: 1, background: 'transparent', color: '#475569', border: '1px solid #1e293b' }}
                >
                  ■ 중지
                </button>
              </div>

              {/* 구간 처리 결과 메시지 — 성공/실패/에러 모두 이 영역에 표시된다 */}
              {segError && (
                <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '4px', lineHeight: 1.4 }}>
                  {segError}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── 현재 모니터링 중인 카메라 목록 ──────────────────── */}
        {/* 모니터링 중인 카메라가 1개 이상일 때만 섹션을 표시한다 */}
        {monitoringList.length > 0 && (
          <div>
            {/* 섹션 타이틀 — 현재 모니터링 중인 카메라 수 표시 */}
            <div style={styles.sectionTitle}>
              🔴 모니터링 중 ({monitoringList.length})
            </div>
            {/* 심각도 순으로 정렬된 카메라를 한 행씩 렌더링 */}
            {monitoringList.map(cam => (
              <MonitoringItem
                key={cam.camera_id}                    // React 재조정용 고유 키
                cam={cam}                              // 카메라 데이터
                selected={selectedId === cam.camera_id} // 현재 선택된 카메라인지 여부
                onSelect={onSelect}                    // 클릭 시 카메라 선택 콜백
              />
            ))}
          </div>
        )}

        {/* ── ITS CCTV 전체 목록 — 접기/펼치기 토글 ────────────── */}
        <div>
          {/* 토글 버튼 — 클릭할 때마다 showAllCctv 가 true ↔ false 전환 */}
          <button
            onClick={() => setShowAllCctv(v => !v)} // 이전 값의 반대로 토글
            style={styles.toggleBtn}
          >
            📷 ITS CCTV 전체 ({cctvList.length}) {/* 전체 CCTV 수 표시 */}
            <span style={{ marginLeft: '4px' }}>{showAllCctv ? '▲' : '▼'}</span> {/* 접기/펼치기 화살표 */}
          </button>

          {/* 펼쳐진 상태일 때만 목록을 렌더링한다 */}
          {showAllCctv && (
            loadingCctv ? (
              <div style={styles.dimText}>로딩 중...</div>      // 로딩 중 안내
            ) : cctvList.length === 0 ? (
              <div style={styles.dimText}>데이터 없음</div>     // 목록이 비어있을 때
            ) : (
              // ITS CCTV 각 항목 렌더링
              cctvList.map(cam => {
                const monData = cameras[cam.camera_id]; // 같은 camera_id 로 모니터링 중인지 확인
                return (
                  <ItsCctvItem
                    key={cam.camera_id}            // React 재조정용 고유 키
                    cam={cam}                      // ITS CCTV 기본 데이터
                    isMonitoring={!!monData}        // 현재 모니터링 중인지 여부 (불리언)
                    monData={monData}              // 모니터링 중이면 실시간 데이터, 아니면 undefined
                    onView={() => onViewItsCctv(cam)} // "보기" 버튼 클릭 시 부모에게 카메라 정보 전달
                  />
                );
              })
            )
          )}
        </div>
      </div>

      {/* 회전 애니메이션 CSS — 학습 중 스피너(⟳)에 사용 */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── IC 드롭다운 컴포넌트 ─────────────────────────────────────────────────────
// label: "시작" 또는 "종료" 텍스트
// value: 현재 선택된 IC 이름
// options: 드롭다운에 표시할 IC 이름 배열
// onChange: 선택 변경 시 부모에게 새 IC 이름을 전달하는 콜백
function IcSelect({ label, value, options, onChange }) {
  return (
    <div style={{ flex: 1 }}> {/* flex:1 로 시작/종료 드롭다운이 공간을 반반 나눔 */}
      {/* 드롭다운 위 레이블 — "시작" 또는 "종료" */}
      <div style={{ fontSize: '9px', color: '#475569', marginBottom: '2px' }}>{label}</div>
      <select
        value={value}                              // 제어 컴포넌트 — value 와 state 를 동기화
        onChange={e => onChange(e.target.value)}   // 사용자가 선택 변경 시 콜백 호출
        style={{
          width: '100%', boxSizing: 'border-box',  // 부모 너비에 맞게 꽉 채움
          background: '#020617', border: '1px solid #1e293b',
          borderRadius: '4px', padding: '3px 4px',
          color: '#e2e8f0', fontSize: '10px', outline: 'none',
        }}
      >
        {/* options 배열을 순회해 각 IC를 option 요소로 만든다 */}
        {options.map(ic => (
          <option key={ic} value={ic}>{ic}</option> // key 와 value 모두 IC 이름 사용
        ))}
      </select>
    </div>
  );
}

// ── 모니터링 중인 카메라 한 행 컴포넌트 ────────────────────────────────────────
// cam: 카메라 데이터 (camera_id, level, is_learning, relearning, location 등)
// selected: 이 카메라가 현재 선택된 카메라인지 여부 → 선택 시 강조 배경과 색 테두리 표시
// onSelect: 행 클릭 시 부모에게 camera_id 를 전달하는 콜백
function MonitoringItem({ cam, selected, onSelect }) {
  const { camera_id, level, is_learning, relearning } = cam; // 필요한 필드만 구조 분해
  // 선택된 카메라: 정체 레벨 색상 테두리 / 미선택: 테두리 없음
  const borderColor = selected ? (LEVEL_COLOR[level] || '#38bdf8') : 'transparent';

  return (
    <div
      onClick={() => onSelect(camera_id)} // 클릭 시 카메라 선택 콜백 호출
      style={{
        padding: '8px 12px', cursor: 'pointer',
        borderBottom: '1px solid #0f172a',
        background: selected ? '#1e293b' : 'transparent', // 선택 시 배경 강조
        borderLeft: `3px solid ${borderColor}`,            // 선택 시 왼쪽 색 테두리
      }}
    >
      {/* 카메라 이름(또는 ID) + 레벨 배지 — 한 줄에 나란히 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
        {/* 카메라 위치 이름 — 없으면 camera_id 로 폴백 */}
        <span style={{ fontSize: '11px', fontWeight: 600, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {cam.location || camera_id}
        </span>
        {/* 정체 레벨 배지 — 학습 중이면 "학습"/"재보정", 아니면 레벨 텍스트 표시 */}
        <LevelBadge level={level} isLearning={is_learning} relearning={relearning} />
      </div>

      {/* 학습 중일 때만 진행률 표시 (예: "학습 중 (30/100)") */}
      {is_learning && (
        <div style={{ marginTop: '4px', fontSize: '9px', color: '#6b7280', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ display: 'inline-block', animation: 'spin 1.2s linear infinite' }}>⟳</span> {/* 회전 아이콘 */}
          학습 중 ({cam.learning_progress}/{cam.learning_total}) {/* 현재/목표 프레임 수 */}
        </div>
      )}
    </div>
  );
}

// ── ITS CCTV 목록 한 행 컴포넌트 ────────────────────────────────────────────
// cam: ITS CCTV 기본 정보 (name, camera_id 등)
// isMonitoring: 현재 모니터링 중인 카메라인지 여부
// monData: 모니터링 중이면 실시간 상태 데이터, 아니면 undefined
// onView: "보기" 버튼 클릭 시 호출할 콜백
function ItsCctvItem({ cam, isMonitoring, monData, onView }) {
  let statusEl = null; // 카메라 상태 표시 요소 — 상황에 따라 아래에서 결정

  if (isMonitoring && monData) {
    if (monData.waiting_stable) {
      // 안정화 대기 중: 카메라가 연결됐지만 아직 안정적인 영상이 확보되지 않은 상태
      statusEl = (
        <div style={{ fontSize: '9px', color: '#f97316', marginTop: '1px', display: 'flex', alignItems: 'center', gap: '3px' }}>
          <span style={{ display: 'inline-block', animation: 'spin 1.2s linear infinite' }}>⟳</span> {/* 회전 스피너 */}
          안정 대기중...
        </div>
      );
    } else if (monData.is_learning || monData.relearning) {
      // 학습 중 또는 재보정 중: 배경학습이 진행되는 동안 정확한 정체 판단을 보류한다
      const prog = monData.learning_progress ?? 0; // 현재 학습 진행 프레임 수
      const tot  = monData.learning_total    ?? 0; // 학습에 필요한 총 프레임 수
      statusEl = (
        <div style={{ fontSize: '9px', color: '#6b7280', marginTop: '1px', display: 'flex', alignItems: 'center', gap: '3px' }}>
          <span style={{ display: 'inline-block', animation: 'spin 1.2s linear infinite' }}>⟳</span>
          {monData.is_learning ? '학습중' : '재보정'} ({prog}/{tot}) {/* 진행률 표시 */}
        </div>
      );
    } else if (monData.level) {
      // 정상 동작 중: 현재 정체 레벨을 색으로 표시한다
      const c = LEVEL_COLOR[monData.level] || '#6b7280'; // 레벨 색상 (없으면 회색)
      statusEl = (
        <div style={{ fontSize: '9px', color: c, marginTop: '1px' }}>
          ● {LEVEL_LABEL[monData.level] || monData.level} {/* "● 원활" 등으로 표시 */}
        </div>
      );
    }
  }

  return (
    <div style={{
      padding: '6px 10px', borderBottom: '1px solid #0f172a',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px',
    }}>
      <div style={{ flex: 1, minWidth: 0 }}> {/* flex:1 로 "보기" 버튼 옆 공간 전부 차지 */}
        {/* 카메라 이름 — 긴 경우 말줄임 처리 */}
        <div style={{ fontSize: '10px', color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {cam.name}
        </div>
        {statusEl} {/* 상태 표시 요소 (안정 대기 / 학습중 / 레벨 중 해당하는 것) */}
      </div>

      {/* "보기" 버튼 — 클릭 시 부모에게 이 카메라 정보를 전달해 지도나 뷰어를 열게 한다 */}
      <button
        onClick={onView}
        style={{
          padding: '2px 7px', borderRadius: '4px', flexShrink: 0, // 버튼이 줄어들지 않게 고정
          background: 'transparent', border: '1px solid #1e293b',
          color: '#64748b', fontSize: '10px', cursor: 'pointer',
        }}
      >
        보기
      </button>
    </div>
  );
}

// ── 정체 레벨 배지 컴포넌트 ─────────────────────────────────────────────────
// level: 현재 정체 레벨 ('SMOOTH' | 'SLOW' | 'CONGESTED' | 'JAM')
// isLearning: 배경 학습 중 여부
// relearning: 재보정 중 여부
function LevelBadge({ level, isLearning, relearning }) {
  // 학습 중 또는 재보정 중에는 레벨 대신 "학습"/"재보정" 배지를 회색으로 표시한다
  if (isLearning || relearning) {
    return (
      <span style={{ ...styles.badge, background: '#374151', color: '#9ca3af', border: '1px solid #4b5563' }}>
        {isLearning ? '학습' : '재보정'} {/* 학습 중이면 "학습", 재보정 중이면 "재보정" */}
      </span>
    );
  }
  // 정상 상태: 레벨에 맞는 색상으로 배지를 표시한다
  const c = LEVEL_COLOR[level] || '#6b7280'; // 레벨 색상 (정의되지 않은 레벨은 회색)
  return (
    <span style={{ ...styles.badge, background: `${c}22`, color: c, border: `1px solid ${c}44` }}>
      {LEVEL_LABEL[level] || '-'} {/* "원활"/"서행"/"정체" 또는 알 수 없을 때 '-' */}
    </span>
  );
}

// ── 공통 스타일 상수 — 여러 곳에서 반복되는 스타일을 한 곳에 모아 관리한다 ───────
const styles = {
  // 최상단 "구간 목록" 헤더 스타일
  header: {
    padding: '10px 12px', borderBottom: '1px solid #1e293b',
    fontSize: '11px', fontWeight: 700, color: '#64748b',
    letterSpacing: '0.06em', flexShrink: 0, // 헤더가 콘텐츠에 밀려 줄어들지 않도록 고정
  },
  // 고속도로 탭 행 스타일
  tabRow: {
    display: 'flex', borderBottom: '1px solid #1e293b', flexShrink: 0, overflowX: 'auto', // 탭이 많으면 가로 스크롤
  },
  // 각 고속도로 탭 버튼 기본 스타일 (선택 상태는 인라인으로 덮어씀)
  tab: {
    flex: 1, padding: '5px 2px', fontSize: '10px', fontWeight: 600,
    cursor: 'pointer', border: 'none', borderRadius: 0, whiteSpace: 'nowrap',
    transition: 'color 0.15s', // 색상 전환 애니메이션
  },
  // 구간 설정 박스 (IC 드롭다운 + 시작/중지 버튼 영역)
  segBox: {
    padding: '8px', borderBottom: '1px solid #1e293b',
    background: '#020617', flexShrink: 0,
  },
  // "구간 모니터링" 레이블 스타일
  segLabel: {
    fontSize: '10px', color: '#475569', fontWeight: 700,
    marginBottom: '6px', letterSpacing: '0.05em',
  },
  // 시작/중지 버튼 공통 스타일 (개별 색상·배경은 인라인으로 덮어씀)
  btn: {
    padding: '5px', borderRadius: '6px', fontSize: '11px',
    fontWeight: 600, cursor: 'pointer', textAlign: 'center',
  },
  // 섹션 타이틀 ("🔴 모니터링 중") 스타일
  sectionTitle: {
    padding: '6px 12px', fontSize: '10px', color: '#ef4444',
    fontWeight: 700, borderBottom: '1px solid #0f172a',
    background: '#0f172a',
  },
  // "ITS CCTV 전체" 접기/펼치기 토글 버튼 스타일
  toggleBtn: {
    width: '100%', padding: '7px 12px', textAlign: 'left',
    background: '#0a1628', border: 'none', borderBottom: '1px solid #1e293b',
    color: '#475569', fontSize: '10px', fontWeight: 700, cursor: 'pointer',
    display: 'flex', alignItems: 'center',
  },
  // 정체 레벨 배지 공통 스타일
  badge: {
    fontSize: '10px', padding: '2px 5px', borderRadius: '8px',
    fontWeight: 600, flexShrink: 0, // 배지가 줄어들지 않도록 고정
  },
  // 로딩 중·데이터 없음 등 흐린 텍스트 스타일
  dimText: {
    padding: '8px 4px', fontSize: '10px', color: '#334155',
  },
};
