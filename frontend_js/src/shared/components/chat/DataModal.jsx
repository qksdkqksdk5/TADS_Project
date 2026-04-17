import { COLUMN_MAP, formatValue } from './columnConfig';

export default function DataModal({ data, onClose }) {
  if (!data) return null;

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={modalContent} onClick={e => e.stopPropagation()}>
        <div style={modalHeader}>
          <h3 style={{ margin: 0 }}>📊 데이터 상세 분석 결과</h3>
          <button onClick={onClose} style={closeBtn}>닫기</button>
        </div>
        <div style={tableWrapper}>
          <table style={dataTable}>
            <thead>
              <tr>
                {Object.keys(data[0]).map(key => (
                  <th key={key} style={tableTh}>{COLUMN_MAP[key] || key}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, idx) => (
                <tr key={idx}>
                  {Object.entries(row).map(([key, val], i) => (
                    <td key={i} style={tableTd}>{formatValue(key, val)}</td>  // ← 여기가 td 렌더링!
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const modalOverlay = { position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.85)', zIndex: 10000, display: 'flex', justifyContent: 'center', alignItems: 'center', backdropFilter: 'blur(4px)' };
const modalContent = { width: '90vw', height: '85vh', background: '#0f172a', borderRadius: '16px', padding: '24px', display: 'flex', flexDirection: 'column', boxShadow: '0 0 40px rgba(0,0,0,0.7)' };
const modalHeader = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', color: '#fff' };
const closeBtn = { background: '#ef4444', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontWeight: 'bold' };
const tableWrapper = { overflow: 'auto', flex: 1, marginTop: '10px', border: '1px solid #1e293b', borderRadius: '8px', background: '#020617' };
const dataTable = { width: '100%', borderCollapse: 'separate', borderSpacing: 0, color: '#e2e8f0' };
const tableTh = { background: '#1e293b', color: '#94a3b8', padding: '15px 20px', fontSize: '13px', fontWeight: 'bold', textTransform: 'uppercase', borderBottom: '2px solid #334155', position: 'sticky', top: 0, zIndex: 10};
const tableTd = { padding: '12px 16px', borderBottom: '1px solid #1e293b', color: '#e2e8f0', whiteSpace: 'nowrap', fontSize: '13px', textAlign: 'center' };