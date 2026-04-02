/* eslint-disable */
// src/modules/plate/components/AnalyticsModal.jsx
import { useState, useEffect } from 'react';
import axios from 'axios';

const PREPROCESS_LABELS = {
  clahe: 'CLAHE', sharpen: '샤프닝',
  denoise: '노이즈제거', morph: '모폴로지',
};

export default function AnalyticsModal({ baseUrl, onClose }) {
  // baseUrl = http://host:5000/api/plate
  // serverUrl = http://host:5000  (이미지 경로용)
  const serverUrl = baseUrl.replace('/api/plate', '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [videoFilter, setVideoFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (videoFilter) params.append('video', videoFilter);
      if (statusFilter) params.append('status', statusFilter);
      if (search) params.append('search', search);
      const res = await axios.get(`${baseUrl}/analytics?${params}`);
      setData(res.data);
    } catch (e) {
      console.error('분석 데이터 로드 실패:', e);
    }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, [videoFilter, statusFilter]);

  const handleSearch = (e) => {
    if (e.key === 'Enter') fetchData();
  };

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.modal} onClick={e => e.stopPropagation()}>

        {/* 헤더 */}
        <div style={s.header}>
          <span style={s.title}>분석 리포트</span>
          <button onClick={onClose} style={s.closeBtn}>✕</button>
        </div>

        {loading ? (
          <div style={s.loadingWrap}>
            <div style={s.loading}>데이터 로드 중...</div>
          </div>
        ) : !data || data.total === 0 ? (
          <div style={s.loadingWrap}>
            <div style={s.loading}>아직 인식 데이터가 없습니다</div>
          </div>
        ) : (
          <>
            {/* 요약 수치 */}
            <div style={s.statRow}>
              <div style={s.statCard}>
                <div style={s.statVal}>{data.total}</div>
                <div style={s.statLabel}>전체 인식</div>
              </div>
              <div style={s.statCard}>
                <div style={s.statVal}>{data.answered}</div>
                <div style={s.statLabel}>정답 입력</div>
              </div>
              <div style={{
                ...s.statCard,
                borderColor: data.accuracy >= 70 ? '#14532d' : '#7f1d1d'
              }}>
                <div style={{
                  ...s.statVal,
                  color: data.accuracy >= 70 ? '#4ade80' : '#f87171'
                }}>
                  {data.accuracy}%
                </div>
                <div style={s.statLabel}>정확도</div>
              </div>
              <div style={s.statCard}>
                <div style={s.statVal}>{data.correct}</div>
                <div style={s.statLabel}>정답</div>
              </div>
            </div>

            {/* 전처리 성공률 */}
            {Object.keys(data.preprocess_stats).length > 0 && (
              <div style={s.section}>
                <div style={s.sectionTitle}>전처리 방법별 보정 성공률</div>
                <div style={s.barWrap}>
                  {Object.entries(data.preprocess_stats).map(([method, stat]) => {
                    const rate = stat.total > 0
                      ? Math.round(stat.success / stat.total * 100) : 0;
                    return (
                      <div key={method} style={s.barRow}>
                        <div style={s.barLabel}>
                          {PREPROCESS_LABELS[method] || method}
                        </div>
                        <div style={s.barTrack}>
                          <div style={{
                            ...s.barFill,
                            width: `${rate}%`,
                            background: rate >= 50
                              ? 'linear-gradient(90deg,#1d4ed8,#3b82f6)'
                              : 'linear-gradient(90deg,#6b7280,#9ca3af)',
                          }} />
                        </div>
                        <div style={s.barPct}>
                          {stat.success}/{stat.total} ({rate}%)
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 필터 */}
            <div style={s.filterRow}>
              <select
                value={videoFilter}
                onChange={e => setVideoFilter(e.target.value)}
                style={s.select}
              >
                <option value=''>전체 영상</option>
                {data.videos.map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
              <select
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                style={s.select}
              >
                <option value=''>전체 상태</option>
                <option value='정답'>✅ 정답</option>
                <option value='오답'>❌ 오답</option>
                <option value='미입력'>— 미입력</option>
              </select>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                onKeyDown={handleSearch}
                placeholder='번호판 검색 (Enter)'
                style={s.searchInput}
              />
            </div>

            {/* 결과 테이블 */}
            <div style={s.tableWrap}>
              <table style={s.table}>
                <thead>
                  <tr>
                    <th style={s.th}>이미지</th>
                    <th style={s.th}>인식 번호판</th>
                    <th style={s.th}>정답</th>
                    <th style={s.th}>정오</th>
                    <th style={s.th}>전처리 결과</th>
                    <th style={s.th}>영상</th>
                    <th style={s.th}>시각</th>
                  </tr>
                </thead>
                <tbody>
                  {data.records.map((r, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #1e293b' }}>
                      <td style={s.td}>
                        {r.img_path ? (
                          <img
                            src={`${serverUrl}${r.img_path}`}
                            style={s.thumb}
                            alt='번호판'
                            onError={e => { e.target.style.display = 'none'; }}
                          />
                        ) : (
                          <div style={s.thumbEmpty}>—</div>
                        )}
                      </td>
                      <td style={{ ...s.td, fontWeight: 700, letterSpacing: '1px', color: '#e2e8f0' }}>
                        {r.plate}
                      </td>
                      <td style={{ ...s.td, color: '#94a3b8' }}>
                        {r.ground_truth || '—'}
                      </td>
                      <td style={s.td}>
                        {r.status === '정답' && <span style={s.badgeGreen}>✅ 정답</span>}
                        {r.status === '오답' && <span style={s.badgeRed}>❌ 오답</span>}
                        {r.status === '미입력' && <span style={s.badgeGray}>— 미입력</span>}
                      </td>
                      <td style={s.td}>
                        {Object.keys(r.preprocess).length === 0 ? (
                          <span style={{ color: '#334155', fontSize: '11px' }}>없음</span>
                        ) : (
                          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                            {Object.entries(r.preprocess).map(([m, p]) => (
                              <span key={m} style={{
                                fontSize: '10px', padding: '2px 6px',
                                borderRadius: '4px', fontWeight: 600,
                                background: p.correct ? 'rgba(34,197,94,0.15)' : 'rgba(71,85,105,0.3)',
                                color: p.correct ? '#4ade80' : '#64748b',
                              }}>
                                {PREPROCESS_LABELS[m] || m}
                                {p.correct ? ' ✔' : ''}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td style={{ ...s.td, fontSize: '11px', color: '#475569' }}>
                        {r.video}
                      </td>
                      <td style={{ ...s.td, fontSize: '11px', color: '#475569', whiteSpace: 'nowrap' }}>
                        {r.detected_at?.split(' ')[1] || r.detected_at}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const s = {
  overlay: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.75)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: '16px',
    width: '1100px', maxWidth: '96vw',
    maxHeight: '92vh',
    display: 'flex', flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '16px 20px',
    borderBottom: '1px solid #1e293b',
    flexShrink: 0,
  },
  title: { fontSize: '16px', fontWeight: 700, color: '#fff' },
  closeBtn: {
    background: 'none', border: 'none', color: '#475569',
    fontSize: '18px', cursor: 'pointer', padding: '4px 8px',
  },
  loadingWrap: {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '60px',
  },
  loading: { color: '#475569', fontSize: '14px' },
  statRow: {
    display: 'flex', gap: '12px', padding: '16px 20px',
    borderBottom: '1px solid #1e293b', flexShrink: 0,
  },
  statCard: {
    flex: 1, background: '#111827', border: '1px solid #1e293b',
    borderRadius: '10px', padding: '12px', textAlign: 'center',
  },
  statVal: {
    fontSize: '26px', fontWeight: 700, color: '#3b82f6',
    fontFamily: 'monospace',
  },
  statLabel: { fontSize: '11px', color: '#475569', marginTop: '4px' },
  section: {
    padding: '14px 20px',
    borderBottom: '1px solid #1e293b',
    flexShrink: 0,
  },
  sectionTitle: { fontSize: '12px', fontWeight: 700, color: '#64748b', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.5px' },
  barWrap: { display: 'flex', flexDirection: 'column', gap: '8px' },
  barRow: { display: 'flex', alignItems: 'center', gap: '10px' },
  barLabel: { width: '70px', fontSize: '12px', color: '#94a3b8', textAlign: 'right', flexShrink: 0 },
  barTrack: { flex: 1, height: '20px', background: '#1e293b', borderRadius: '4px', overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: '4px', transition: 'width 0.6s ease', minWidth: '2px' },
  barPct: { fontSize: '11px', color: '#64748b', width: '80px', flexShrink: 0 },
  filterRow: {
    display: 'flex', gap: '10px', padding: '12px 20px',
    borderBottom: '1px solid #1e293b', flexShrink: 0,
  },
  select: {
    background: '#1e293b', color: '#e0e0ff',
    border: '1px solid #334155', borderRadius: '8px',
    padding: '6px 10px', fontSize: '12px', cursor: 'pointer',
  },
  searchInput: {
    flex: 1, background: '#1e293b', color: '#e0e0ff',
    border: '1px solid #334155', borderRadius: '8px',
    padding: '6px 12px', fontSize: '12px',
  },
  tableWrap: { flex: 1, overflowY: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '13px' },
  th: {
    background: '#0f172a', color: '#64748b',
    padding: '10px 14px', textAlign: 'left',
    fontSize: '11px', fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.5px',
    position: 'sticky', top: 0,
    borderBottom: '1px solid #1e293b',
  },
  td: { padding: '10px 14px', color: '#94a3b8', verticalAlign: 'middle' },
  thumb: { width: '80px', height: '36px', objectFit: 'cover', borderRadius: '4px' },
  thumbEmpty: { width: '80px', height: '36px', background: '#1e293b', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#334155', fontSize: '12px' },
  badgeGreen: { background: 'rgba(34,197,94,0.15)', color: '#4ade80', padding: '2px 8px', borderRadius: '100px', fontSize: '11px', fontWeight: 600 },
  badgeRed: { background: 'rgba(239,68,68,0.15)', color: '#f87171', padding: '2px 8px', borderRadius: '100px', fontSize: '11px', fontWeight: 600 },
  badgeGray: { background: 'rgba(71,85,105,0.3)', color: '#64748b', padding: '2px 8px', borderRadius: '100px', fontSize: '11px', fontWeight: 600 },
};