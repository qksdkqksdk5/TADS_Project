/* eslint-disable */
// SLOW / JAM 진입 시점부터 경과 시간 카운트업
// levelSince: useMonitoringSocket이 레벨 전환 시 기록한 ms 타임스탬프
//   → 사용자가 패널을 나중에 열어도 사건 발생 시점부터 올바르게 경과 표시
// SMOOTH 복귀 시 자동 리셋

import { useState, useEffect } from 'react';

export default function useGoldenTimer(level, levelSince) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const isActive = level === 'SLOW' || level === 'JAM' || level === 'CONGESTED';

    if (!isActive) {
      setElapsed(0);
      return;
    }

    // levelSince가 있으면 사건 발생 시각 기준, 없으면 지금부터
    const startMs = levelSince ?? Date.now();
    const update = () => setElapsed(Math.floor((Date.now() - startMs) / 1000));
    update();  // 즉시 1회 실행 (패널 열자마자 올바른 값 표시)
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [level, levelSince]);

  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const ss = String(elapsed % 60).padStart(2, '0');

  return { elapsed, formatted: `${mm}:${ss}` };
}
