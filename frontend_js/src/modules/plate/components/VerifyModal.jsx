/* eslint-disable */
// src/modules/plate/components/VerifyModal.jsx
// 정답 입력 + 전처리 재인식 모달

import { useState } from 'react';

export default function VerifyModal({ plate, baseUrl, preprocessMethods, onVerify, onReprocess, onClose }) {
  const [gtInput, setGtInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isEditing, setIsEditing] = useState(false); // ✅ 재입력 모드

  const handleVerify = async () => {
    if (!gtInput.trim()) return;
    setLoading(true);
    await onVerify(plate.id, gtInput.trim());
    setLoading(false);
    setIsEditing(false); // ✅ 재입력 완료 후 편집 모드 종료
    setGtInput('');
  };

  const handleEditStart = () => {
    setGtInput(plate.ground_truth || ''); // ✅ 기존 정답으로 input 초기화
    setIsEditing(true);
  };

  const handleReprocess = async (method) => {
    setLoading(true);
    await onReprocess(plate.id, method);
    setLoading(false);
  };

  // 정답 입력 영역: 미입력 or 재입력 모드면 input, 아니면 결과 표시
  const isInputMode = plate.is_correct === null || plate.is_correct === undefined || isEditing;

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.modal} onClick={e => e.stopPropagation()}>

        {/* 헤더 */}
        <div style={s.header}>
          <span style={s.headerTitle}>🔍 번호판 검증 — ID: {plate.id}</span>
          <button onClick={onClose} style={s.closeBtn}>✕</button>
        </div>

        {/* 이미지 비교 */}
        <div style={s.imgRow}>
          <div style={s.imgBox}>
            <div style={s.imgLabel}>원본</div>
            {plate.img_url
              ? <img src={`${baseUrl}${plate.img_url}`} style={s.img} alt="원본" />
              : <div style={s.imgEmpty}>이미지 없음</div>
            }
          </div>
          {plate.proc_img_url && (
            <div style={s.imgBox}>
              <div style={s.imgLabel}>전처리 ({plate.preprocess})</div>
              <img src={`${baseUrl}${plate.proc_img_url}`} style={s.img} alt="전처리" />
            </div>
          )}
        </div>

        {/* 인식 결과 */}
        <div style={s.section}>
          <div style={s.sectionLabel}>인식 결과</div>
          {plate.char_diff ? (
            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
              {plate.char_diff.map((c, i) => (
                <span key={i} style={{
                  padding: '4px 8px',
                  borderRadius: '6px',
                  fontSize: '20px',
                  fontWeight: 700,
                  background: c.correct ? '#14532d' : '#7f1d1d',
                  color: c.correct ? '#4ade80' : '#f87171',
                }}>
                  {c.recognized}
                </span>
              ))}
              <span style={{ fontSize: '12px', color: '#475569', alignSelf: 'center', marginLeft: '8px' }}>
                정답: {plate.ground_truth}
              </span>
            </div>
          ) : (
            <span style={{
              fontSize: '24px', fontWeight: 700, letterSpacing: '3px',
              color: plate.is_fixed ? '#00ff00' : '#00d7ff'
            }}>
              {plate.text}
            </span>
          )}
        </div>

        {/* 재인식 결과 */}
        {plate.retried_text && (
          <div style={s.section}>
            <div style={s.sectionLabel}>재인식 결과</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{
                fontSize: '20px', fontWeight: 700, letterSpacing: '2px',
                color: plate.retry_correct === true ? '#4ade80'
                     : plate.retry_correct === false ? '#f87171' : '#00d7ff'
              }}>
                {plate.retried_text}
              </span>
              {plate.retry_correct === true && (
                <span style={{ color: '#4ade80', fontSize: '13px', fontWeight: 600 }}>✔ 보정 성공</span>
              )}
              {plate.retry_correct === false && (
                <span style={{ color: '#f87171', fontSize: '13px', fontWeight: 600 }}>✗ 보정 실패</span>
              )}
            </div>
          </div>
        )}

        {/* 정답 입력 */}
        <div style={s.section}>
          <div style={s.sectionLabel}>정답 입력</div>

          {isInputMode ? (
            // ✅ 입력 모드 (최초 입력 or 재입력)
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                value={gtInput}
                onChange={e => setGtInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleVerify()}
                placeholder="예: 38조4129"
                style={s.input}
                autoFocus
              />
              <button
                onClick={handleVerify}
                disabled={loading || !gtInput.trim()}
                style={{
                  ...s.verifyBtn,
                  opacity: (loading || !gtInput.trim()) ? 0.5 : 1,
                  cursor: (loading || !gtInput.trim()) ? 'not-allowed' : 'pointer',
                }}
              >
                {loading ? '확인 중...' : '확인'}
              </button>
              {/* ✅ 재입력 모드일 때만 취소 버튼 표시 */}
              {isEditing && (
                <button
                  onClick={() => { setIsEditing(false); setGtInput(''); }}
                  style={s.cancelBtn}
                >
                  취소
                </button>
              )}
            </div>
          ) : (
            // ✅ 결과 표시 모드 + 수정 버튼
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '13px', color: '#94a3b8' }}>{plate.ground_truth}</span>
              {plate.is_correct
                ? <span style={{ color: '#4ade80', fontWeight: 700 }}>✔ 정답</span>
                : <span style={{ color: '#f87171', fontWeight: 700 }}>✗ 오답</span>
              }
              {/* ✅ 재입력 버튼 */}
              <button onClick={handleEditStart} style={s.editBtn}>
                ✏️ 수정
              </button>
            </div>
          )}
        </div>

        {/* 전처리 재인식 — 오답일 때만 */}
        {plate.is_correct === false && (
          <div style={s.section}>
            <div style={s.sectionLabel}>🔧 전처리 재인식 비교</div>

            <div style={s.preprocessGrid}>
              {preprocessMethods.map(m => {
                const done = plate.preprocess_results?.[m.key];
                return (
                  <button
                    key={m.key}
                    onClick={() => handleReprocess(m.key)}
                    disabled={loading}
                    style={{
                      ...s.preprocessBtn,
                      background: done ? '#0f2744' : '#1e293b',
                      border: done ? '1px solid #3b82f6' : '1px solid #334155',
                      opacity: loading ? 0.6 : 1,
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: '2px' }}>
                      {done ? '✔ ' : ''}{m.label}
                    </div>
                    <div style={{ fontSize: '10px', color: '#64748b' }}>{m.desc}</div>
                  </button>
                );
              })}
            </div>

            {plate.preprocess_results && Object.keys(plate.preprocess_results).length > 0 && (
              <div style={{ marginTop: '12px' }}>
                <div style={{ fontSize: '11px', color: '#475569', marginBottom: '6px' }}>
                  결과 비교 (정답: {plate.ground_truth || '미입력'})
                </div>
                <table style={s.table}>
                  <thead>
                    <tr>
                      <th style={s.th}>방법</th>
                      <th style={s.th}>인식 결과</th>
                      <th style={s.th}>정오</th>
                      <th style={s.th}>시간</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={s.td}>원본</td>
                      <td style={{ ...s.td, fontWeight: 700, color: '#00d7ff' }}>{plate.text}</td>
                      <td style={s.td}>
                        {plate.is_correct === true
                          ? <span style={{ color: '#4ade80' }}>✔</span>
                          : <span style={{ color: '#f87171' }}>✗</span>}
                      </td>
                      <td style={{ ...s.td, color: '#475569' }}>—</td>
                    </tr>
                    {Object.entries(plate.preprocess_results).map(([method, r]) => (
                      <tr key={method}>
                        <td style={s.td}>
                          {preprocessMethods.find(m => m.key === method)?.label || method}
                        </td>
                        <td style={{
                          ...s.td, fontWeight: 700,
                          color: r.correct === true ? '#4ade80'
                               : r.correct === false ? '#f87171' : '#00d7ff'
                        }}>
                          {r.text}
                        </td>
                        <td style={s.td}>
                          {r.correct === true
                            ? <span style={{ color: '#4ade80' }}>✔</span>
                            : r.correct === false
                              ? <span style={{ color: '#f87171' }}>✗</span>
                              : <span style={{ color: '#475569' }}>—</span>}
                        </td>
                        <td style={{ ...s.td, color: '#475569' }}>{r.elapsed_ms}ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div style={{ marginTop: '10px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {Object.entries(plate.preprocess_results).map(([method, r]) => (
                    <div key={method} style={{ flex: '1 1 45%' }}>
                      <div style={{ fontSize: '10px', color: '#475569', marginBottom: '3px' }}>
                        {preprocessMethods.find(m => m.key === method)?.label || method}
                        {r.correct === true && <span style={{ color: '#4ade80' }}> ✔</span>}
                        {r.correct === false && <span style={{ color: '#f87171' }}> ✗</span>}
                      </div>
                      <img
                        src={`${baseUrl}${r.img_url}`}
                        style={{ width: '100%', height: '55px', objectFit: 'cover', borderRadius: '6px' }}
                        alt={method}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}

const s = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.7)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: '16px',
    padding: '24px',
    width: '480px',
    maxWidth: '90vw',
    maxHeight: '85vh',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerTitle: { fontSize: '16px', fontWeight: 700, color: '#fff' },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: '#475569',
    fontSize: '18px',
    cursor: 'pointer',
    padding: '4px 8px',
    borderRadius: '6px',
  },
  imgRow: { display: 'flex', gap: '12px' },
  imgBox: { flex: 1 },
  imgLabel: { fontSize: '11px', color: '#475569', marginBottom: '4px' },
  img: { width: '100%', height: '80px', objectFit: 'cover', borderRadius: '8px' },
  imgEmpty: {
    width: '100%', height: '80px', background: '#1e293b',
    borderRadius: '8px', display: 'flex',
    alignItems: 'center', justifyContent: 'center',
    color: '#475569', fontSize: '12px',
  },
  section: {
    borderTop: '1px solid #1e293b',
    paddingTop: '12px',
  },
  sectionLabel: { fontSize: '12px', color: '#64748b', marginBottom: '8px', fontWeight: 600 },
  input: {
    flex: 1,
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: '8px',
    padding: '8px 12px',
    color: '#e0e0ff',
    fontSize: '14px',
  },
  verifyBtn: {
    background: '#6366f1',
    color: 'white',
    border: 'none',
    borderRadius: '8px',
    padding: '8px 16px',
    fontSize: '13px',
    fontWeight: 600,
    flexShrink: 0,
  },
  // ✅ 수정 버튼
  editBtn: {
    background: 'none',
    border: '1px solid #334155',
    borderRadius: '6px',
    padding: '4px 10px',
    color: '#64748b',
    fontSize: '12px',
    cursor: 'pointer',
    marginLeft: 'auto',
  },
  // ✅ 취소 버튼
  cancelBtn: {
    background: 'none',
    border: '1px solid #334155',
    borderRadius: '8px',
    padding: '8px 12px',
    color: '#64748b',
    fontSize: '13px',
    cursor: 'pointer',
    flexShrink: 0,
  },
  preprocessGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '8px',
  },
  preprocessBtn: {
    color: '#94a3b8',
    borderRadius: '8px',
    padding: '10px 12px',
    fontSize: '12px',
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'all 0.2s',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '12px',
  },
  th: {
    background: '#1e293b',
    color: '#64748b',
    padding: '6px 8px',
    textAlign: 'left',
    fontWeight: 600,
    borderBottom: '1px solid #334155',
  },
  td: {
    padding: '6px 8px',
    borderBottom: '1px solid #1e293b',
    color: '#94a3b8',
  },
};