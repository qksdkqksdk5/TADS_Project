/* eslint-disable */
import React, { useState, useEffect } from 'react';
import { fetchStatsSummary, fetchStatsHistory } from '../api';

const getOrigin = (host) => {
  if (host.startsWith('http')) return host;
  const outsideHost = 'itsras.illit.kr';
  return host === outsideHost ? `https://${host}` : `http://${host}:5000`;
};

function StatsPanel({ isMobile, host }) {
  const [viewMode, setViewMode] = useState("summary");
  const [dataMode, setDataMode] = useState("real");
  const [stats, setStats] = useState({
    total: 0, correct: 0, incorrect: 0, precision: 0,
    typeData: { fire: 0, reverse: 0, manual: 0 }
  });
  const [historyLogs, setHistoryLogs] = useState([]);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);

  // 불필요했던 hourlyData(더미데이터) 삭제

  useEffect(() => {
    const load = async () => {
      try {
        const response = await fetchStatsSummary(host, dataMode);
        setStats({
          total: response.data.total,
          correct: response.data.correct,
          incorrect: response.data.incorrect,
          precision: response.data.precision,
          typeData: response.data.type_counts || { fire: 0, reverse: 0, manual: 0 }
        });
      } catch (err) { console.error("통계 로드 실패:", err); }
    };
    load();
    if (viewMode === "summary") {
      const interval = setInterval(load, 5000);
      return () => clearInterval(interval);
    }
  }, [host, viewMode, dataMode]);

  useEffect(() => {
    if (viewMode === "history") {
      const load = async () => {
        try {
          const response = await fetchStatsHistory(host, selectedDate, dataMode);
          setHistoryLogs(response.data.logs);
        } catch (err) { console.error("이력 로드 실패:", err); }
      };
      load();
    }
  }, [viewMode, selectedDate, host, dataMode]);

  const calculatePercent = (count) => {
    const sum = stats.typeData.fire + stats.typeData.reverse + stats.typeData.manual;
    return sum > 0 ? (count / sum) * 100 : 0;
  };

  return (
    <div style={mainContainerStyle}>
      <header style={headerStyle}>
        <div>
          <h1 style={titleStyle}>📊 데이터 분석 센터</h1>
          <div style={dataModeGroup}>
            {["real", "sim", "all"].map((mode) => (
              <button key={mode} onClick={() => setDataMode(mode)}
                style={dataMode === mode ? activeDataBtn : inactiveDataBtn}>
                {mode === "real" ? "실제 운영" : mode === "sim" ? "시뮬레이션" : "전체 데이터"}
              </button>
            ))}
          </div>
        </div>
        <div style={tabGroupStyle}>
          <button onClick={() => setViewMode("summary")} style={viewMode === "summary" ? activeTabBtn : inactiveTabBtn}>통계 요약</button>
          <button onClick={() => setViewMode("history")} style={viewMode === "history" ? activeTabBtn : inactiveTabBtn}>상세 이력</button>
        </div>
      </header>

      {viewMode === "summary" ? (
        <div style={contentLayout}>
          {/* 1. 상단 하이라이트 카드 */}
          <div style={statGrid(isMobile)}>
            <div style={statCardStyle}>
              <div style={statTitleStyle}>전체 분석량</div>
              <div style={statValueStyle}>{stats.total.toLocaleString()}<span style={unitStyle}>건</span></div>
            </div>
            <div style={{ ...statCardStyle, borderTop: '4px solid #22c55e' }}>
              <div style={statTitleStyle}>정탐 (Success)</div>
              <div style={{ ...statValueStyle, color: '#22c55e' }}>{stats.correct}</div>
            </div>
            <div style={{ ...statCardStyle, borderTop: '4px solid #f87171' }}>
              <div style={statTitleStyle}>오탐 (False Alarm)</div>
              <div style={{ ...statValueStyle, color: '#f87171' }}>{stats.incorrect}</div>
            </div>
            <div style={{ ...statCardStyle, borderTop: '4px solid #6366f1' }}>
              <div style={statTitleStyle}>모델 신뢰도</div>
              <div style={{ ...statValueStyle, color: '#6366f1' }}>{stats.precision}<span style={unitStyle}>%</span></div>
            </div>
          </div>

          {/* 2. 중앙 분석 섹션 (1단 세로 막대형 차트로 전면 개편) */}
          <div style={analysisRow(isMobile)}>
            <div style={singlePanelWrapper}>
              <h4 style={panelTitleStyle}>🔥 이벤트 유형 통계 분포</h4>
              
              <div style={verticalChartContainer}>
                {['fire', 'reverse', 'manual'].map(type => (
                  <div key={type} style={verticalBarWrapper}>
                    {/* 상단: 건수 표시 */}
                    <div style={{
                      ...verticalBarCount, 
                      color: type === 'fire' ? '#ef4444' : type === 'reverse' ? '#f59e0b' : '#3b82f6'
                    }}>
                      {stats.typeData[type]}건
                    </div>
                    
                    {/* 중앙: 세로 막대 트랙 */}
                    <div style={verticalBarTrack}>
                      <div style={{ 
                        ...verticalBarFill, 
                        height: `${Math.max(calculatePercent(stats.typeData[type]), 2)}%`, // 최소 2% 높이 보장
                        background: type === 'fire' ? 'linear-gradient(180deg, #ef4444, #7f1d1d)' : 
                                    type === 'reverse' ? 'linear-gradient(180deg, #f59e0b, #78350f)' : 
                                    'linear-gradient(180deg, #3b82f6, #1e3a8a)' 
                      }} />
                    </div>
                    
                    {/* 하단: 라벨 */}
                    <div style={verticalBarLabel}>
                      {type === 'fire' ? '화재 감지' : type === 'reverse' ? '역주행 감지' : '수동 기록'}
                    </div>
                  </div>
                ))}
              </div>

            </div>
          </div>

          {/* 3. 하단 인사이트 패널 */}
          <div style={insightPanel}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
              <span style={{ fontSize: '20px' }}>💡</span>
              <h4 style={{ margin: 0, color: '#60a5fa', fontSize: '16px' }}>Model Feedback Insight</h4>
            </div>
            <p style={insightText}>
              현재 <b style={{color: '#fff'}}>{dataMode === 'real' ? "실제 운영" : dataMode === 'sim' ? "시뮬레이션" : "전체 누적"}</b> 데이터를 분석 중입니다.
              피드백 데이터는 AI 모델 재학습 파이프라인에 자동으로 반영되어 시스템의 정확도를 지속적으로 개선합니다.
            </p>
          </div>
        </div>
      ) : (
        /* 상세 이력 뷰 */
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
          <div style={filterBar}>
            <span style={{ color: '#94a3b8', fontSize: '14px' }}>날짜 필터:</span>
            <input type="date" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} style={datePickerStyle} />
          </div>
          <div style={logListContainer}>
            {historyLogs.length === 0 ? (
              <div style={emptyStyle}>조회된 이력이 없습니다.</div>
            ) : (
              historyLogs.map(log => (
                <div key={log.id} style={historyCardStyle}>
                  <div style={historyImageWrapper}>
                    {log.image_path ? (
                      <img src={`${getOrigin(host)}${log.image_path}`} style={historyImage} alt="event"
                        onClick={() => window.open(`${getOrigin(host)}${log.image_path}`)} />
                    ) : <div style={noImgStyle}>No Image</div>}
                  </div>
                  <div style={historyInfo}>
                    <div style={logHeader}>
                      <span style={{ ...typeBadge, background: log.type === 'manual' ? '#1e3a8a' : '#450a0a', color: log.type === 'manual' ? '#60a5fa' : '#f87171' }}>
                        {log.type.toUpperCase()}
                      </span>
                      <span style={logTime}>{log.time}</span>
                    </div>
                    <div style={historyAddress}>{log.address}</div>
                    <div style={historyMemo}>"{log.memo || log.feedback_msg || "메모 없음"}"</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ================= CSS & Styles =================

const mainContainerStyle = { 
  width: '100%', 
  height: '100vh',
  padding: '32px', 
  background: '#020617', 
  boxSizing: 'border-box', 
  color: '#fff', 
  display: 'flex', 
  flexDirection: 'column', 
  gap: '24px',
  overflow: 'hidden'
};

const headerStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', flexShrink: 0 };
const titleStyle = { fontSize: '32px', fontWeight: '800', margin: 0, letterSpacing: '-1px', color: '#f8fafc' };

const dataModeGroup = { display: 'flex', gap: '8px', marginTop: '12px' };
const contentLayout = { 
  display: 'flex', 
  flexDirection: 'column', 
  gap: '24px', 
  flex: 1,
  minHeight: 0
};

const statGrid = (isMobile) => ({
  display: 'grid',
  gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(4, 1fr)',
  gap: '20px',
  flexShrink: 0
});

const statCardStyle = { 
  background: '#0f172a', padding: '20px 24px', borderRadius: '16px', 
  border: '1px solid #1e293b', transition: 'transform 0.2s',
  display: 'flex', flexDirection: 'column', justifyContent: 'center'
};

const statTitleStyle = { color: '#94a3b8', fontSize: '13px', fontWeight: '600', marginBottom: '8px' };
const statValueStyle = { fontSize: '32px', fontWeight: '800', display: 'flex', alignItems: 'baseline', gap: '6px' };
const unitStyle = { fontSize: '14px', color: '#475569' };

const analysisRow = (isMobile) => ({
  display: 'flex',
  flexDirection: 'column', // 무조건 세로로 채움
  alignItems: 'center',
  flex: 1,
  minHeight: 0,
  width: '100%'
});

const singlePanelWrapper = { 
  background: '#0f172a', 
  borderRadius: '24px', 
  border: '1px solid #1e293b', 
  padding: '40px', 
  display: 'flex', 
  flexDirection: 'column',
  flex: 1,
  width: '100%',
  maxWidth: '1700px' // 너무 좌우로 찢어지는 현상 방지
};

const panelTitleStyle = { 
  color: '#f1f5f9', fontSize: '18px', fontWeight: '700', marginBottom: '20px', 
  marginTop: 0, display: 'flex', alignItems: 'center' 
};

/* --- 세로형 차트를 위한 신규 스타일 --- */
const verticalChartContainer = {
  flex: 1,
  display: 'flex',
  justifyContent: 'center',
  alignItems: 'flex-end',
  gap: '15%', // 막대 사이의 간격
  padding: '20px 0 40px 0',
  minHeight: '200px'
};

const verticalBarWrapper = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  height: '100%',
  justifyContent: 'flex-end',
  width: '120px' // 컬럼 하나의 전체 너비 영역
};

const verticalBarCount = {
  fontSize: '28px',
  fontWeight: '800',
  marginBottom: '16px',
  textShadow: '0 2px 10px rgba(0,0,0,0.5)' // 숫자 강조를 위한 그림자
};

const verticalBarTrack = {
  width: '70px', // 실제 막대의 두께 (두툼하게 설정)
  height: '100%', 
  background: '#1e293b',
  borderRadius: '16px 16px 0 0', // 위쪽만 둥글게
  display: 'flex',
  flexDirection: 'column',
  justifyContent: 'flex-end',
  overflow: 'hidden',
  boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.5)' // 음각 효과
};

const verticalBarFill = {
  width: '100%',
  transition: 'height 1s cubic-bezier(0.4, 0, 0.2, 1)',
  borderRadius: '16px 16px 0 0', // 차오를 때도 위쪽 둥글게
};

const verticalBarLabel = {
  marginTop: '20px',
  fontSize: '16px',
  color: '#cbd5e1',
  fontWeight: '700'
};
/* ------------------------------------- */

const insightPanel = { 
  background: 'linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)', 
  padding: '24px 32px', 
  borderRadius: '20px', 
  border: '1px solid #312e81',
  flexShrink: 0
};
const insightText = { color: '#94a3b8', fontSize: '14px', lineHeight: '1.6', margin: 0 };

/* 공통/이력 탭 스타일 (기존 유지) */
const tabGroupStyle = { background: '#0f172a', padding: '4px', borderRadius: '12px', border: '1px solid #1e293b', display: 'flex' };
const baseTabBtn = { padding: '10px 24px', borderRadius: '10px', fontSize: '14px', fontWeight: '700', cursor: 'pointer', border: 'none', transition: '0.2s' };
const activeTabBtn = { ...baseTabBtn, background: '#2563eb', color: '#fff' };
const inactiveTabBtn = { ...baseTabBtn, background: 'transparent', color: '#64748b' };
const dataBtnBase = { padding: '6px 12px', borderRadius: '8px', fontSize: '12px', fontWeight: '600', cursor: 'pointer', border: '1px solid #1e293b', background: 'transparent', color: '#64748b' };
const activeDataBtn = { ...dataBtnBase, background: '#1e293b', color: '#fff', borderColor: '#3b82f6' };
const inactiveDataBtn = { ...dataBtnBase };

/* 상세이력 탭 스타일 */
const logListContainer = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '20px' };
const historyCardStyle = { background: '#0f172a', borderRadius: '16px', border: '1px solid #1e293b', overflow: 'hidden', display: 'flex', height: '150px' };
const historyImageWrapper = { width: '150px', height: '150px', flexShrink: 0, background: '#000' };
const historyImage = { width: '100%', height: '100%', objectFit: 'cover', cursor: 'pointer' };
const historyInfo = { flex: 1, padding: '18px', display: 'flex', flexDirection: 'column', gap: '10px' };
const logHeader = { display: 'flex', justifyContent: 'space-between', alignItems: 'center' };
const logTime = { fontSize: '11px', color: '#64748b' };
const historyAddress = { fontSize: '14px', color: '#f1f5f9', fontWeight: '600', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' };
const historyMemo = { fontSize: '12px', color: '#94a3b8', fontStyle: 'italic', background: '#1e293b', padding: '6px 10px', borderRadius: '6px' };
const typeBadge = { fontSize: '10px', padding: '4px 8px', borderRadius: '6px', fontWeight: '800' };
const filterBar = { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '10px' };
const datePickerStyle = { background: '#0f172a', border: '1px solid #334155', color: '#fff', padding: '8px 12px', borderRadius: '10px' };
const emptyStyle = { gridColumn: '1 / -1', textAlign: 'center', padding: '100px', color: '#475569' };
const noImgStyle = { height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#334155', fontSize: '12px' };

export default StatsPanel;