/* eslint-disable */
// src/modules/monitoring/index.jsx
import { useState } from 'react';
import axios from 'axios';

export default function MonitoringModule({ host }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const checkHealth = async () => {
    setLoading(true);
    setStatus(null);
    try {
      const res = await axios.get(`http://${host || window.location.hostname}:5000/api/monitoring/health`);
      setStatus(res.data.status === 'ok' ? 'ok' : 'error');
    } catch {
      setStatus('error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ flex: 1, padding: '32px', background: '#0f0f1a', minHeight: '100vh', color: '#e0e0ff' }}>
      <div style={{ maxWidth: '900px', margin: '0 auto', border: '1px dashed #2d4d3d', borderRadius: '12px', padding: '48px', textAlign: 'center' }}>
        <div style={{ fontSize: '48px', marginBottom: '16px' }}>🚦</div>
        <h1 style={{ fontSize: '24px', fontWeight: 700, marginBottom: '8px', color: '#fff' }}>교통 정체 흐름</h1>
        <p style={{ color: '#406050', fontSize: '14px', marginBottom: '32px' }}>이 영역을 개발해주세요</p>

        <div style={{ marginBottom: '32px' }}>
          <button onClick={checkHealth} disabled={loading} style={{ background: loading ? '#2a2a4a' : '#22c55e22', border: '1px solid #22c55e', color: loading ? '#6060a0' : '#22c55e', padding: '10px 28px', borderRadius: '8px', fontSize: '14px', fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer' }}>
            {loading ? '확인 중...' : '🔌 백엔드 연결 확인'}
          </button>
          {status === 'ok'    && <div style={{ marginTop: '12px', color: '#22c55e', fontSize: '13px', fontWeight: 600 }}>✅ 연결 성공! <code style={{ color: '#86efac' }}>/api/monitoring/health</code> 응답 OK</div>}
          {status === 'error' && <div style={{ marginTop: '12px', color: '#f87171', fontSize: '13px', fontWeight: 600 }}>❌ 연결 실패 — 백엔드 서버가 실행 중인지 확인하세요</div>}
        </div>

        <div style={{ background: '#1a1a2e', borderRadius: '8px', padding: '24px', textAlign: 'left', fontSize: '13px', color: '#8080b0' }}>
          <p style={{ marginBottom: '8px', color: '#a0a0d0', fontWeight: 600 }}>📌 개발 가이드</p>
          <ul style={{ paddingLeft: '20px', lineHeight: '2' }}>
            <li>백엔드: <code>backend_flask/modules/monitoring/</code> 폴더에 라우트 추가</li>
            <li>프론트: 이 파일(<code>src/modules/monitoring/index.jsx</code>)에 UI 개발</li>
            <li>API 연동: <code>src/modules/monitoring/api.js</code> 파일 생성 후 axios 호출</li>
            <li>사이드바: <code>src/shared/components/Sidebar.jsx</code> — 이미 등록됨 ✅</li>
            <li>라우팅: <code>src/modules/traffic/index.jsx</code> — 이미 등록됨 ✅</li>
          </ul>
        </div>
      </div>
    </div>
  );
}