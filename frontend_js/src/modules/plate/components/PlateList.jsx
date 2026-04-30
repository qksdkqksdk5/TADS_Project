/* eslint-disable */
// src/modules/plate/components/PlateList.jsx
// 실시간 / 전체기록 탭 패널

import { useState } from 'react';
import PlateCard from './PlateCard';
import VerifyModal from './VerifyModal';

export default function PlateList({
  plates, allResults, resultVideos, videoFilter, onVideoFilter,
  baseUrl, preprocessMethods, onVerify, onReprocess
}) {
  const [activeView, setActiveView] = useState('live');
  const [modalPlate, setModalPlate] = useState(null); // 모달에 표시할 번호판

  // 모달에서 verify/reprocess 후 allResults 업데이트 반영
  const handleVerify = async (id, gt) => {
    await onVerify(id, gt);
    // modalPlate 갱신 (allResults에서 최신 데이터 반영)
    setModalPlate(prev => prev ? { ...prev, ground_truth: gt } : null);
  };

  const handleReprocess = async (id, method) => {
    await onReprocess(id, method);
  };

  // allResults에서 최신 modalPlate 데이터 동기화
  const syncedModalPlate = modalPlate
    ? allResults.find(r => r.id === modalPlate.id) || modalPlate
    : null;

  return (
    <div style={s.panel}>
      {/* 탭 */}
      <div style={s.tabRow}>
        {['live', 'history'].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveView(tab)}
            style={{
              ...s.tabBtn,
              borderBottom: activeView === tab ? '2px solid #6366f1' : '2px solid transparent',
              color: activeView === tab ? '#818cf8' : '#606080',
            }}
          >
            {tab === 'live'
              ? `실시간 (${plates.length})`
              : `전체 기록 (${allResults.length})`
            }
          </button>
        ))}
      </div>

      {/* 리스트 */}
      <div style={s.list}>
        {activeView === 'live' && (
          plates.length === 0
            ? <p style={s.empty}>인식 중...</p>
            : plates.map(p => (
              <PlateCard key={p.id} plate={p} baseUrl={baseUrl} />
            ))
        )}

        {activeView === 'history' && (
          <>
            {resultVideos && resultVideos.length > 1 && (
              <select
                value={videoFilter}
                onChange={e => onVideoFilter(e.target.value)}
                style={s.videoSelect}
              >
                <option value=''>전체 영상</option>
                {resultVideos.map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            )}
            {allResults.length === 0
              ? <p style={s.empty}>아직 인식된 번호판이 없습니다</p>
              : allResults.map((r, i) => (
                <PlateCard
                  key={`${r.id}-${i}`}
                  plate={r}
                  baseUrl={baseUrl}
                  showTime
                  onClick={() => setModalPlate(r)}
                />
              ))
            }
          </>
        )}
      </div>

      {/* 모달 */}
      {syncedModalPlate && (
        <VerifyModal
          plate={syncedModalPlate}
          baseUrl={baseUrl}
          preprocessMethods={preprocessMethods}
          onVerify={handleVerify}
          onReprocess={handleReprocess}
          onClose={() => setModalPlate(null)}
        />
      )}
    </div>
  );
}

const s = {
  panel: {
    width: '300px',
    flexShrink: 0,
    minHeight: 0,
    background: '#1a1a2e',
    borderRadius: '12px',
    border: '1px solid #1e293b',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  tabRow: { display: 'flex', borderBottom: '1px solid #2a2a4a', flexShrink: 0 },
  tabBtn: {
    flex: 1, background: 'none', border: 'none',
    padding: '12px', fontSize: '13px', fontWeight: 600,
    cursor: 'pointer', transition: 'all 0.2s',
  },
  list: { flex: 1, overflowY: 'auto', padding: '12px' },
  empty: { color: '#606080', fontSize: '13px', textAlign: 'center', marginTop: '40px' },
  videoSelect: {
    width: '100%', background: '#0f0f1a',
    color: '#94a3b8', border: '1px solid #1e293b',
    borderRadius: '8px', padding: '7px 10px',
    fontSize: '12px', cursor: 'pointer',
    marginBottom: '10px',
  },
};