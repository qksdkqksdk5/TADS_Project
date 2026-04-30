import { useEffect, useState } from 'react';
import axios from 'axios';
import { Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip
} from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip);

const INTENT_COLORS = {
  SQL: '#6366f1',
  RAG: '#10b981',
  BOTH: '#f59e0b',
  UNKNOWN: '#6b7280'
};

export default function LLMDashboard({ host }) {
  const [cases, setCases] = useState([]);
  const [kpi, setKpi] = useState({
    accuracy: 0,
    total: 0,
    correct: 0
  });

  useEffect(() => {
    fetchLogs();
    fetchKpi();
  }, []);

  const fetchLogs = async () => {
    try {
      const res = await axios.get(`http://${host}:5000/api/chat/llm/logs`);
      setCases(res.data.logs || []);
    } catch (err) {
      console.error("로그 불러오기 실패", err);
    }
  };

  const fetchKpi = async () => {
    try {
      const res = await axios.get(`http://${host}:5000/api/chat/llm/kpi`);
      setKpi(res.data);
    } catch (err) {
      console.error("KPI 불러오기 실패", err);
    }
  };

  // ✅ expected 수정
  const updateExpected = async (id, newValue) => {
    const prev = [...cases];

    setCases(cases.map(c =>
      c.id === id ? { ...c, expected: newValue } : c
    ));

    try {
      await axios.patch(
        `http://${host}:5000/api/chat/llm/logs/${id}`,
        { expected: newValue }
      );
      fetchKpi(); // 🔥 KPI 갱신
    } catch (err) {
      console.error("expected 수정 실패", err);
      setCases(prev);
    }
  };

  // ======================
  // 📊 기본 지표
  // ======================
  const n = cases.length;

  const avgLat = n
    ? Math.round(cases.reduce((a, c) => a + (c.latency || 0), 0) / n)
    : 0;

  const slowCount = cases.filter(c => c.latency > 2500).length;

  // ======================
  // 📊 차트 데이터
  // ======================
  const intentAvg = {};
  ['SQL', 'RAG', 'BOTH', 'UNKNOWN'].forEach(k => {
    const grp = cases.filter(c => (c.expected || "UNKNOWN") === k && c.latency);
    if (grp.length) {
      intentAvg[k] = Math.round(
        grp.reduce((a, c) => a + c.latency, 0) / grp.length
      );
    }
  });

  const chartLabels = Object.keys(intentAvg);
  const chartData = {
    labels: chartLabels,
    datasets: [{
      data: chartLabels.map(k => intentAvg[k]),
      backgroundColor: chartLabels.map(k => INTENT_COLORS[k]),
      borderRadius: 6,
    }]
  };

  return (
    <div style={styles.root}>

      {/* 헤더 */}
      <div style={styles.header}>
        <h2 style={styles.title}>TADS LLM 성능 지표</h2>
        <p style={styles.sub}>
          {n}건 로그 / 평균 {avgLat} ms
        </p>
      </div>

      {/* KPI 카드 */}
      <div style={styles.cardRow}>
        <div style={styles.card}>
          <div style={styles.cardLabel}>총 요청</div>
          <div style={styles.cardValue}>{n}</div>
        </div>

        <div style={styles.card}>
          <div style={styles.cardLabel}>평균 응답</div>
          <div style={styles.cardValue}>{avgLat}ms</div>
        </div>

        <div style={styles.card}>
          <div style={styles.cardLabel}>느린 응답</div>
          <div style={styles.cardValue}>{slowCount}</div>
        </div>

        <div style={styles.card}>
          <div style={styles.cardLabel}>정확도</div>
          <div style={styles.cardValue}>{kpi.accuracy}%</div>
        </div>
      </div>

      {/* 차트 */}
      <div style={styles.chartBox}>
        <Bar data={chartData} options={{
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            y: {
              ticks: { color: '#9ca3af' },
              grid: { color: 'rgba(255,255,255,0.05)' }
            },
            x: {
              ticks: { color: '#9ca3af' },
              grid: { display: false }
            }
          }
        }} />
      </div>

      {/* 리스트 */}
      <div style={styles.list}>
        {cases.map((c, i) => {
          const expected = c.expected || "UNKNOWN";
          const isCorrect = expected === c.actual;

          return (
            <div key={i} style={styles.item(isCorrect)}>
              <div style={styles.q}>{c.q}</div>

              <div style={styles.row}>
                {/* expected */}
                <select
                  value={expected}
                  onChange={(e) => updateExpected(c.id, e.target.value)}
                  style={styles.select}
                >
                  <option value="SQL">SQL</option>
                  <option value="RAG">RAG</option>
                  <option value="BOTH">BOTH</option>
                  <option value="UNKNOWN">UNKNOWN</option>
                </select>

                {/* actual */}
                <span style={styles.actual}>
                  → {c.actual}
                </span>

                {/* latency */}
                <span style={styles.latency}>
                  {c.latency} ms
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ======================
// 🎨 스타일
// ======================

const glass = {
  background: 'rgba(15,23,42,0.6)',
  border: '1px solid rgba(255,255,255,0.06)',
  backdropFilter: 'blur(10px)',
};

const styles = {
  root: {
    padding: '24px',
    color: '#fff',
    fontFamily: 'Inter, sans-serif',
  },

  header: {
    marginBottom: '20px'
  },

  title: {
    fontSize: '22px',
    fontWeight: '700'
  },

  sub: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: '13px'
  },

  cardRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)', // 🔥 4개
    gap: '12px',
    marginBottom: '20px'
  },

  card: {
    ...glass,
    borderRadius: '12px',
    padding: '18px'
  },

  cardLabel: {
    fontSize: '12px',
    color: 'rgba(255,255,255,0.4)'
  },

  cardValue: {
    fontSize: '20px',
    fontWeight: '700',
    marginTop: '6px'
  },

  chartBox: {
    ...glass,
    borderRadius: '12px',
    padding: '20px',
    height: '260px',
    marginBottom: '20px'
  },

  list: {
    ...glass,
    borderRadius: '12px',
    overflow: 'hidden'
  },

  item: (correct) => ({
    padding: '14px 16px',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
    background: correct
      ? 'rgba(16,185,129,0.05)'  // 정답
      : 'rgba(239,68,68,0.05)'   // 오답
  }),

  q: {
    fontSize: '14px',
    marginBottom: '6px'
  },

  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px'
  },

  select: {
    background: 'rgba(15,23,42,0.9)',
    color: '#fff',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '6px',
    padding: '4px 8px',
    fontSize: '12px',
    cursor: 'pointer'
  },

  actual: {
    fontSize: '12px',
    color: 'rgba(255,255,255,0.5)'
  },

  latency: {
    marginLeft: 'auto',
    fontSize: '12px',
    color: '#f87171'
  }
};