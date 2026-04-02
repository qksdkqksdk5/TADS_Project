/* eslint-disable */
// src/modules/plate/components/ControlBox.jsx
import { useState } from 'react';

export default function ControlBox({ connected, videos, onStart, onAnalytics }) {
  const [selectedVideo, setSelectedVideo] = useState(videos[0] || '');
  const [started, setStarted] = useState(false);

  if (videos.length > 0 && !selectedVideo) {
    setSelectedVideo(videos[0]);
  }

  const handleStart = async () => {
    await onStart(selectedVideo);
    setStarted(true);
  };

  const canStart = connected && !!selectedVideo;

  return (
    <div style={s.box}>
      <div style={s.row}>
        <select
          value={selectedVideo}
          onChange={e => setSelectedVideo(e.target.value)}
          style={s.select}
          disabled={!connected || videos.length === 0}
        >
          {videos.length === 0
            ? <option>영상 없음 (test 폴더에 mp4 추가)</option>
            : videos.map(v => <option key={v} value={v}>{v}</option>)
          }
        </select>
        <button
          onClick={handleStart}
          disabled={!canStart}
          style={{
            ...s.btn,
            background: canStart ? '#6366f1' : '#2a2a4a',
            color: canStart ? 'white' : '#606080',
            cursor: canStart ? 'pointer' : 'not-allowed',
          }}
        >
          {started ? '▶ 재시작' : '▶ 시작'}
        </button>
        <button
          onClick={onAnalytics}
          style={s.analyticsBtn}
        >
          분석하기
        </button>
      </div>
    </div>
  );
}

const s = {
  box: {
    background: '#111827',
    borderRadius: '12px',
    border: '1px solid #1e293b',
    padding: '10px 14px',
    flexShrink: 0,
  },
  row: { display: 'flex', gap: '8px', alignItems: 'center' },
  select: {
    flex: 1,
    background: '#1e293b', color: '#e0e0ff',
    border: '1px solid #334155', borderRadius: '8px',
    padding: '8px 12px', fontSize: '13px', cursor: 'pointer',
  },
  btn: {
    padding: '8px 18px', border: 'none',
    borderRadius: '8px', fontSize: '13px',
    fontWeight: 'bold', flexShrink: 0, transition: 'all 0.2s',
  },
  analyticsBtn: {
    padding: '8px 14px',
    border: '1px solid #2a3a4a',
    borderRadius: '8px',
    fontSize: '12px',
    fontWeight: 600,
    background: 'transparent',
    color: '#64748b',
    cursor: 'pointer',
    flexShrink: 0,
    letterSpacing: '0.5px',
    transition: 'all 0.2s',
  },
};