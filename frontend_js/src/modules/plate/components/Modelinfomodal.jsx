/* eslint-disable */
import { useState } from 'react';

const MODELS = {
  detection: {
    label: '번호판 탐지',
    name: 'YOLO11n',
    color: '#7c6fff',
    accent: '#a89fff',
    metrics: [
      { key: 'mAP@50',      value: '95.9%' },
      { key: 'mAP@50-95',   value: '59.6%' },
      { key: 'Precision',   value: '91.5%' },
      { key: 'Recall',      value: '91.4%' },
    ],
    speed: [
      { key: '추론 속도',     value: '2.3ms' },
      { key: '총 처리 시간',  value: '4.4ms' },
      { key: '처리 FPS',     value: '~227 FPS' },
    ],
    training: [
      { key: '학습 이미지',   value: '1,190장' },
      { key: '검증 이미지',   value: '172장' },
      { key: 'Epoch',        value: '80' },
      { key: '학습 시간',     value: '0.493h' },
      { key: '파라미터 수',   value: '2.58M' },
      { key: '모델 크기',     value: '5.5MB' },
      { key: '클래스 수',     value: '1개 (번호판)' },
      { key: '학습 GPU',      value: 'Tesla T4' },
    ],
  },
  ocr: {
    label: '문자 인식 (OCR)',
    name: 'YOLOv8n',
    color: '#00c8a0',
    accent: '#00ffcc',
    metrics: [
      { key: 'mAP@50',      value: '99.2%' },
      { key: 'mAP@50-95',   value: '96.0%' },
      { key: 'Precision',   value: '98.3%' },
      { key: 'Recall',      value: '98.1%' },
    ],
    speed: [
      { key: '추론 속도',     value: '1.2ms' },
      { key: '총 처리 시간',  value: '2.8ms' },
      { key: '처리 FPS',     value: '~357 FPS' },
    ],
    training: [
      { key: '학습 이미지',   value: '3,606장' },
      { key: '검증 이미지',   value: '554장' },
      { key: 'Epoch',        value: '100' },
      { key: '학습 시간',     value: '1.814h' },
      { key: '파라미터 수',   value: '3.06M' },
      { key: '모델 크기',     value: '6.4MB' },
      { key: '클래스 수',     value: '70개 (숫자·한글)' },
      { key: '학습 GPU',      value: 'Tesla T4' },
    ],
  },
};

const PIPELINE = [
  { step: '01', label: '영상 입력',    desc: 'Video Frame' },
  { step: '02', label: '번호판 탐지',  desc: 'YOLO11n' },
  { step: '03', label: '영역 크롭',    desc: 'Crop & Resize' },
  { step: '04', label: '문자 인식',    desc: 'YOLOv8n OCR' },
  { step: '05', label: '결과 출력',    desc: 'Plate Number' },
];

export default function ModelInfoModal({ onClose }) {
  const [tab, setTab] = useState('detection');
  const model = MODELS[tab];

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.modal} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={s.header}>
          <span style={s.title}>모델 정보</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        {/* Pipeline */}
        <div style={s.pipelineWrap}>
          {PIPELINE.map((p, i) => (
            <div key={p.step} style={s.pipelineRow}>
              <div style={s.pipelineItem}>
                <span style={s.pipelineStep}>{p.step}</span>
                <span style={s.pipelineLabel}>{p.label}</span>
                <span style={s.pipelineDesc}>{p.desc}</span>
              </div>
              {i < PIPELINE.length - 1 && (
                <span style={s.pipelineArrow}>▶</span>
              )}
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div style={s.tabs}>
          {Object.entries(MODELS).map(([key, m]) => (
            <button
              key={key}
              style={{ ...s.tab, ...(tab === key ? { ...s.tabActive, borderColor: m.color, color: m.color } : {}) }}
              onClick={() => setTab(key)}
            >
              {m.name}
              <span style={{ ...s.tabBadge, background: tab === key ? m.color + '22' : 'transparent', color: m.color }}>
                {m.label}
              </span>
            </button>
          ))}
        </div>

        {/* Content */}
        <div style={s.content}>

          {/* 성능 지표 */}
          <Section title="성능 지표" color={model.color}>
            <div style={s.metricsGrid}>
              {model.metrics.map(m => (
                <div key={m.key} style={{ ...s.metricCard, borderColor: model.color + '44' }}>
                  <span style={{ ...s.metricValue, color: model.color }}>{m.value}</span>
                  <span style={s.metricKey}>{m.key}</span>
                </div>
              ))}
            </div>
          </Section>

          {/* 처리 속도 */}
          <Section title="처리 속도 (Tesla T4)" color={model.color}>
            <div style={s.speedGrid}>
              {model.speed.map(m => (
                <div key={m.key} style={s.speedRow}>
                  <span style={s.speedKey}>{m.key}</span>
                  <div style={s.speedBarWrap}>
                    <div style={{ ...s.speedBar, background: model.color, width: getBarWidth(m.key) }} />
                  </div>
                  <span style={{ ...s.speedVal, color: model.accent }}>{m.value}</span>
                </div>
              ))}
            </div>
          </Section>

          {/* 학습 정보 */}
          <Section title="학습 정보" color={model.color}>
            <div style={s.infoGrid}>
              {model.training.map(m => (
                <div key={m.key} style={s.infoRow}>
                  <span style={s.infoKey}>{m.key}</span>
                  <span style={s.infoVal}>{m.value}</span>
                </div>
              ))}
            </div>
          </Section>

        </div>
      </div>
    </div>
  );
}

function Section({ title, color, children }) {
  return (
    <div style={s.section}>
      <div style={{ ...s.sectionTitle, color }}>
        <span style={{ ...s.sectionDot, background: color }} />
        {title}
      </div>
      {children}
    </div>
  );
}

function getBarWidth(key) {
  const map = { '추론 속도': '30%', '총 처리 시간': '55%', '처리 FPS': '90%' };
  return map[key] || '50%';
}

const s = {
  overlay: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.7)',
    backdropFilter: 'blur(4px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    background: '#13131f',
    border: '1px solid #2a2a40',
    borderRadius: '16px',
    width: '720px',
    maxWidth: '95vw',
    maxHeight: '90vh',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
  },

  // Header
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '20px 24px 16px',
    borderBottom: '1px solid #1e1e30',
  },
  title: {
    fontSize: '16px', fontWeight: 600, color: '#e0e0ff', letterSpacing: '0.05em',
  },
  closeBtn: {
    background: 'none', border: 'none', color: '#666', cursor: 'pointer',
    fontSize: '16px', padding: '4px 8px', borderRadius: '6px',
    transition: 'color 0.2s',
  },

  // Pipeline
  pipelineWrap: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    flexWrap: 'wrap',
    gap: '4px',
    padding: '16px 24px',
    borderBottom: '1px solid #1e1e30',
    background: '#0f0f1a',
  },
  pipelineRow: {
    display: 'flex', alignItems: 'center', gap: '4px',
  },
  pipelineItem: {
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    background: '#1a1a2e', border: '1px solid #2a2a44',
    borderRadius: '8px', padding: '8px 12px', minWidth: '80px',
  },
  pipelineStep: {
    fontSize: '10px', color: '#555', fontFamily: 'monospace', marginBottom: '2px',
  },
  pipelineLabel: {
    fontSize: '11px', fontWeight: 600, color: '#c0c0e0', marginBottom: '2px',
  },
  pipelineDesc: {
    fontSize: '10px', color: '#666',
  },
  pipelineArrow: {
    color: '#333', fontSize: '10px',
  },

  // Tabs
  tabs: {
    display: 'flex', gap: '0',
    borderBottom: '1px solid #1e1e30',
  },
  tab: {
    flex: 1, background: 'none', border: 'none',
    borderBottom: '2px solid transparent',
    color: '#555', cursor: 'pointer',
    padding: '12px 16px',
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
    fontSize: '14px', fontWeight: 600,
    transition: 'all 0.2s',
  },
  tabActive: {
    background: 'rgba(124,111,255,0.05)',
  },
  tabBadge: {
    fontSize: '10px', fontWeight: 400,
    padding: '2px 8px', borderRadius: '20px',
    transition: 'all 0.2s',
  },

  // Content
  content: {
    padding: '16px 24px 24px',
    display: 'flex', flexDirection: 'column', gap: '20px',
  },
  section: {
    display: 'flex', flexDirection: 'column', gap: '10px',
  },
  sectionTitle: {
    fontSize: '12px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
    display: 'flex', alignItems: 'center', gap: '8px',
  },
  sectionDot: {
    width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
  },

  // Metrics
  metricsGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px',
  },
  metricCard: {
    background: '#0f0f1a', border: '1px solid',
    borderRadius: '10px', padding: '12px 10px',
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px',
  },
  metricValue: {
    fontSize: '20px', fontWeight: 700, fontFamily: 'monospace',
  },
  metricKey: {
    fontSize: '10px', color: '#666',
  },

  // Speed
  speedGrid: {
    display: 'flex', flexDirection: 'column', gap: '8px',
  },
  speedRow: {
    display: 'flex', alignItems: 'center', gap: '10px',
  },
  speedKey: {
    fontSize: '12px', color: '#888', width: '90px', flexShrink: 0,
  },
  speedBarWrap: {
    flex: 1, height: '4px', background: '#1e1e30', borderRadius: '2px', overflow: 'hidden',
  },
  speedBar: {
    height: '100%', borderRadius: '2px', transition: 'width 0.6s ease',
  },
  speedVal: {
    fontSize: '13px', fontWeight: 600, fontFamily: 'monospace', width: '80px', textAlign: 'right',
  },

  // Info grid
  infoGrid: {
    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px',
  },
  infoRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    background: '#0f0f1a', borderRadius: '8px', padding: '8px 12px',
  },
  infoKey: {
    fontSize: '12px', color: '#666',
  },
  infoVal: {
    fontSize: '12px', color: '#c0c0e0', fontWeight: 500,
  },
};