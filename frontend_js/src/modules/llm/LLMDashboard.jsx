import { useState } from 'react';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip
} from 'chart.js';
import { COLUMN_MAP, formatValue } from './columnConfig';
import DataModal from './DataModal';

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip);

const INTENT_COLORS = { SQL: '#378ADD', RAG: '#1D9E75', BOTH: '#EF9F27', UNKNOWN: '#888780' };

const INITIAL_CASES = [
  { q: '이번주 화재 결과 보여줘',      expected: 'SQL',  actual: 'SQL',     latency: 1120, sqlResult: 'ok',    summary: '총 3건 확인됨',       score: null },
  { q: '역주행 대응 절차 알려줘',      expected: 'RAG',  actual: 'RAG',     latency: 890,  sqlResult: '',      summary: '1~4단계 안내',        score: null },
  { q: '최근 역주행 사진이랑 설명도',  expected: 'BOTH', actual: 'BOTH',    latency: 2340, sqlResult: 'ok',    summary: '이미지+절차 제공',     score: null },
  { q: 'TADS가 뭐야?',                expected: 'RAG',  actual: 'RAG',     latency: 760,  sqlResult: '',      summary: '시스템 개요 설명',     score: null },
  { q: 'test06 영상 번호판 찾아줘',   expected: 'SQL',  actual: 'SQL',     latency: 1580, sqlResult: 'ok',    summary: '2건 확인됨',          score: null },
  { q: '아까 내 질문이 뭐였어?',      expected: 'RAG',  actual: 'SQL',     latency: 950,  sqlResult: '',      summary: '이전 대화 조회 시도',  score: null },
  { q: '오늘 실제 화재 있었어?',      expected: 'SQL',  actual: 'SQL',     latency: 1380, sqlResult: 'empty', summary: '조회 결과 없음',       score: null },
  { q: '안녕',                        expected: 'RAG',  actual: 'RAG',     latency: 620,  sqlResult: '',      summary: '기능 안내 제공',       score: null },
];

const BADGE = {
  SQL:     { bg: '#E6F1FB', color: '#185FA5' },
  RAG:     { bg: '#E1F5EE', color: '#0F6E56' },
  BOTH:    { bg: '#FAEEDA', color: '#854F0B' },
  UNKNOWN: { bg: '#F1EFE8', color: '#5F5E5A' },
};

function Badge({ intent, size = 11 }) {
  const s = BADGE[intent] || BADGE.UNKNOWN;
  return (
    <span style={{
      background: s.bg, color: s.color,
      fontSize: size, padding: '2px 7px', borderRadius: 100, fontWeight: 500, display: 'inline-block'
    }}>{intent}</span>
  );
}

function latGrade(ms) {
  if (!ms) return { label: '—', bg: '#F1EFE8', color: '#5F5E5A' };
  if (ms < 1000) return { label: '빠름', bg: '#EAF3DE', color: '#3B6D11' };
  if (ms < 2500) return { label: '보통', bg: '#F1EFE8', color: '#5F5E5A' };
  return { label: '느림', bg: '#FCEBEB', color: '#A32D2D' };
}

export default function LLMDashboard({ host }) {
  const [cases, setCases] = useState(INITIAL_CASES);
  const [tab, setTab] = useState('manual');
  const [modalData, setModalData] = useState(null);
  const [newCase, setNewCase] = useState({
    q: '', expected: 'SQL', actual: '', latency: '', sqlResult: '', summary: ''
  });

  const setScore = (idx, val) => {
    setCases(prev => prev.map((c, i) =>
      i === idx ? { ...c, score: c.score === val ? null : val } : c
    ));
  };

  const setActual = (idx, val) => {
    setCases(prev => prev.map((c, i) => i === idx ? { ...c, actual: val } : c));
  };

  const addCase = () => {
    if (!newCase.q.trim()) return;
    setCases(prev => [...prev, { ...newCase, latency: parseInt(newCase.latency) || null, score: null }]);
    setNewCase({ q: '', expected: 'SQL', actual: '', latency: '', sqlResult: '', summary: '' });
  };

  // 지표 계산
  const n = cases.length;
  const scored = cases.filter(c => c.score !== null);
  const good = scored.filter(c => c.score === 'good');
  const autoAnswered = cases.filter(c => c.actual);
  const autoCorrect = autoAnswered.filter(c => c.actual === c.expected);
  const sqlCases = cases.filter(c => (c.expected === 'SQL' || c.expected === 'BOTH') && c.sqlResult);
  const sqlOk = sqlCases.filter(c => c.sqlResult === 'ok');
  const withLat = cases.filter(c => c.latency);
  const avgLat = withLat.length ? Math.round(withLat.reduce((a, c) => a + c.latency, 0) / withLat.length) : null;

  // Intent 분포
  const intentCount = { SQL: 0, RAG: 0, BOTH: 0, UNKNOWN: 0 };
  cases.forEach(c => { intentCount[c.expected] = (intentCount[c.expected] || 0) + 1; });

  // 차트 데이터
  const intentAvg = {};
  ['SQL', 'RAG', 'BOTH', 'UNKNOWN'].forEach(k => {
    const grp = cases.filter(c => c.expected === k && c.latency);
    if (grp.length) intentAvg[k] = Math.round(grp.reduce((a, c) => a + c.latency, 0) / grp.length);
  });
  const chartLabels = Object.keys(intentAvg);
  const chartData = {
    labels: chartLabels,
    datasets: [{
      data: chartLabels.map(k => intentAvg[k]),
      backgroundColor: chartLabels.map(k => INTENT_COLORS[k]),
      borderRadius: 4,
    }]
  };

  const tabs = ['manual', 'auto', 'latency', 'add'];
  const tabLabels = { manual: '수동 평가', auto: '자동 채점', latency: '응답 시간', add: '케이스 추가' };

  return (
    <div style={{ padding: '1.5rem', fontFamily: 'sans-serif' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 500 }}>TADS LLM 성능 지표</h2>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: '#64748b' }}>실시간 평가 대시보드 · gpt-4o-mini</p>
        </div>
        <span style={{ background: '#F1EFE8', color: '#5F5E5A', fontSize: 12, padding: '4px 10px', borderRadius: 100, fontWeight: 500 }}>{n}건 평가됨</span>
      </div>

      {/* 지표 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: '1.25rem' }}>
        {[
          { label: '응답 품질 (수동)', value: scored.length ? Math.round(good.length / scored.length * 100) + '%' : '—', sub: `${good.length} / ${scored.length}건` },
          { label: 'Intent 정확도', value: autoAnswered.length ? Math.round(autoCorrect.length / autoAnswered.length * 100) + '%' : '—', sub: `${autoCorrect.length} / ${autoAnswered.length}건` },
          { label: '평균 응답 시간', value: avgLat ? avgLat + 'ms' : '—', sub: withLat.length + '건 평균' },
          { label: 'SQL 성공률', value: sqlCases.length ? Math.round(sqlOk.length / sqlCases.length * 100) + '%' : '—', sub: `${sqlOk.length} / ${sqlCases.length}건` },
        ].map(m => (
          <div key={m.label} style={{ background: '#f8fafc', borderRadius: 8, padding: '14px 16px' }}>
            <p style={{ margin: '0 0 4px', fontSize: 12, color: '#64748b' }}>{m.label}</p>
            <p style={{ margin: 0, fontSize: 22, fontWeight: 500 }}>{m.value}</p>
            <p style={{ margin: '3px 0 0', fontSize: 11, color: '#94a3b8' }}>{m.sub}</p>
          </div>
        ))}
      </div>

      {/* 탭 */}
      <div style={{ display: 'flex', borderBottom: '1px solid #e2e8f0', marginBottom: '1.25rem' }}>
        {tabs.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            padding: '8px 14px', fontSize: 13, cursor: 'pointer', border: 'none', background: 'none',
            color: tab === t ? '#0f172a' : '#64748b', fontWeight: tab === t ? 500 : 400,
            borderBottom: tab === t ? '2px solid #0f172a' : '2px solid transparent', marginBottom: -1,
          }}>{tabLabels[t]}</button>
        ))}
      </div>

      {/* 수동 평가 */}
      {tab === 'manual' && (
        <div>
          {/* Intent 분포 바 */}
          <div style={{ display: 'flex', gap: 12, marginBottom: '1rem' }}>
            {Object.entries(intentCount).map(([k, cnt]) => (
              <div key={k} style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{k}</div>
                <div style={{ height: 5, borderRadius: 3, background: '#e2e8f0', overflow: 'hidden' }}>
                  <div style={{ height: '100%', borderRadius: 3, background: INTENT_COLORS[k], width: n ? (cnt / n * 100) + '%' : '0%', transition: 'width .5s' }} />
                </div>
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{cnt}건 ({n ? Math.round(cnt / n * 100) : 0}%)</div>
              </div>
            ))}
          </div>

          {/* 테이블 */}
          <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 70px 90px 80px 70px', gap: 10, padding: '8px 16px', background: '#f8fafc', fontSize: 11, color: '#94a3b8', fontWeight: 500, textTransform: 'uppercase' }}>
              <span>질문</span><span>Intent</span><span>AI 응답 요약</span><span>수동 평가</span><span>SQL 결과</span>
            </div>
            {cases.map((c, i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 70px 90px 80px 70px', gap: 10, padding: '10px 16px', borderTop: '1px solid #f1f5f9', alignItems: 'center', fontSize: 13 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.q}>{c.q}</span>
                <span><Badge intent={c.expected} /></span>
                <span style={{ fontSize: 12, color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.summary || '—'}</span>
                <span style={{ display: 'flex', gap: 4 }}>
                  {['good', 'bad'].map(v => (
                    <button key={v} onClick={() => setScore(i, v)} style={{
                      width: 28, height: 28, borderRadius: '50%', cursor: 'pointer', fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      border: '1px solid #e2e8f0',
                      background: c.score === v ? (v === 'good' ? '#EAF3DE' : '#FCEBEB') : '#fff',
                      color: c.score === v ? (v === 'good' ? '#3B6D11' : '#A32D2D') : '#64748b',
                    }}>{v === 'good' ? '✓' : '✗'}</button>
                  ))}
                </span>
                <span>
                  {c.sqlResult === 'ok' ? <span style={{ background: '#EAF3DE', color: '#3B6D11', fontSize: 11, padding: '2px 7px', borderRadius: 100 }}>있음</span>
                    : c.sqlResult === 'empty' ? <span style={{ background: '#FCEBEB', color: '#A32D2D', fontSize: 11, padding: '2px 7px', borderRadius: 100 }}>없음</span>
                    : <span style={{ color: '#cbd5e1', fontSize: 12 }}>—</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 자동 채점 */}
      {tab === 'auto' && (
        <div>
          <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 90px 110px 40px', gap: 10, padding: '8px 16px', background: '#f8fafc', fontSize: 11, color: '#94a3b8', fontWeight: 500, textTransform: 'uppercase' }}>
              <span>질문</span><span>예상 Intent</span><span>실제 LLM Intent</span><span>결과</span>
            </div>
            {cases.map((c, i) => {
              const correct = c.actual && c.actual === c.expected;
              return (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 90px 110px 40px', gap: 10, padding: '10px 16px', borderTop: '1px solid #f1f5f9', alignItems: 'center', fontSize: 13 }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.q}</span>
                  <span><Badge intent={c.expected} /></span>
                  <select value={c.actual} onChange={e => setActual(i, e.target.value)} style={{ fontSize: 12, padding: '4px 6px', borderRadius: 6, border: '1px solid #e2e8f0' }}>
                    <option value="">—</option>
                    {['SQL', 'RAG', 'BOTH', 'UNKNOWN'].map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                  <span style={{ textAlign: 'center', fontSize: 16 }}>
                    {c.actual ? (correct ? '✅' : '❌') : '·'}
                  </span>
                </div>
              );
            })}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: '1rem' }}>
            {[
              { label: '정답률', value: autoAnswered.length ? Math.round(autoCorrect.length / autoAnswered.length * 100) + '%' : '—', color: '#1D9E75' },
              { label: '오답 건수', value: autoAnswered.length ? (autoAnswered.length - autoCorrect.length) + '건' : '—', color: '#E24B4A' },
              { label: '미채점', value: (cases.length - autoAnswered.length) + '건', color: undefined },
            ].map(m => (
              <div key={m.label} style={{ background: '#f8fafc', borderRadius: 8, padding: '14px 16px' }}>
                <p style={{ margin: '0 0 4px', fontSize: 12, color: '#64748b' }}>{m.label}</p>
                <p style={{ margin: 0, fontSize: 22, fontWeight: 500, color: m.color }}>{m.value}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 응답 시간 */}
      {tab === 'latency' && (
        <div>
          <div style={{ marginBottom: '1rem', height: 200 }}>
            <Bar data={chartData} options={{
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                y: { beginAtZero: true, ticks: { callback: v => v + 'ms' } },
                x: { grid: { display: false } }
              }
            }} />
          </div>
          <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 70px 90px 80px', gap: 10, padding: '8px 16px', background: '#f8fafc', fontSize: 11, color: '#94a3b8', fontWeight: 500, textTransform: 'uppercase' }}>
              <span>질문</span><span>Intent</span><span>응답 시간</span><span>등급</span>
            </div>
            {cases.map((c, i) => {
              const g = latGrade(c.latency);
              return (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 70px 90px 80px', gap: 10, padding: '10px 16px', borderTop: '1px solid #f1f5f9', alignItems: 'center', fontSize: 13 }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.q}</span>
                  <span><Badge intent={c.expected} /></span>
                  <span style={{ fontWeight: 500 }}>{c.latency ? c.latency + 'ms' : '—'}</span>
                  <span><span style={{ background: g.bg, color: g.color, fontSize: 11, padding: '2px 7px', borderRadius: 100, fontWeight: 500 }}>{g.label}</span></span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 케이스 추가 */}
      {tab === 'add' && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: '1.25rem' }}>
          <p style={{ margin: '0 0 1rem', fontSize: 14, fontWeight: 500 }}>새 테스트 케이스 추가</p>
          <div style={{ display: 'grid', gap: 10 }}>
            <div>
              <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>질문</label>
              <input value={newCase.q} onChange={e => setNewCase(p => ({ ...p, q: e.target.value }))} placeholder="예: 이번주 화재 결과 보여줘" style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
              {[
                { label: '예상 Intent', key: 'expected', type: 'select', opts: ['SQL','RAG','BOTH','UNKNOWN'] },
                { label: '응답 시간 (ms)', key: 'latency', type: 'number', placeholder: '예: 1240' },
                { label: 'SQL 결과', key: 'sqlResult', type: 'select', opts: [['', '해당 없음'], ['ok', '데이터 있음'], ['empty', '데이터 없음']] },
              ].map(f => (
                <div key={f.key}>
                  <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>{f.label}</label>
                  {f.type === 'select'
                    ? <select value={newCase[f.key]} onChange={e => setNewCase(p => ({ ...p, [f.key]: e.target.value }))} style={{ width: '100%', padding: '7px 8px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
                        {f.opts.map(o => Array.isArray(o) ? <option key={o[0]} value={o[0]}>{o[1]}</option> : <option key={o} value={o}>{o}</option>)}
                      </select>
                    : <input type={f.type} value={newCase[f.key]} onChange={e => setNewCase(p => ({ ...p, [f.key]: e.target.value }))} placeholder={f.placeholder} style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
                  }
                </div>
              ))}
            </div>
            <div>
              <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>AI 응답 요약</label>
              <input value={newCase.summary} onChange={e => setNewCase(p => ({ ...p, summary: e.target.value }))} placeholder="예: 총 3건 확인됨" style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
            </div>
            <div>
              <label style={{ fontSize: 12, color: '#64748b', display: 'block', marginBottom: 4 }}>실제 LLM Intent</label>
              <select value={newCase.actual} onChange={e => setNewCase(p => ({ ...p, actual: e.target.value }))} style={{ width: '100%', padding: '7px 8px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
                <option value="">미입력</option>
                {['SQL','RAG','BOTH','UNKNOWN'].map(v => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <button onClick={addCase} style={{ padding: '9px 16px', fontSize: 13, borderRadius: 8, border: 'none', background: '#0f172a', color: '#fff', cursor: 'pointer', fontWeight: 500 }}>케이스 추가 ↗</button>
          </div>
        </div>
      )}

      {/* DataModal */}
      <DataModal data={modalData} onClose={() => setModalData(null)} host={host} />
    </div>
  );
}