/* eslint-disable */
// src/modules/monitoring/hooks/useSoundAlert.js
// Web Audio API 기반 사운드 알림 — 별도 음원 파일 없이 브라우저가 직접 소리를 생성

import { useEffect, useRef, useCallback } from 'react';

export function useSoundAlert(soundOn) {
  const ctxRef              = useRef(null);
  const wrongwayTimerRef    = useRef(null);
  const congestionTimerRef  = useRef(null);

  // AudioContext 싱글턴 반환
  const getCtx = useCallback(() => {
    if (!ctxRef.current) {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    return ctxRef.current;
  }, []);

  // 기본 삐 소리 재생
  const playBeep = useCallback((freq, duration, volume = 0.4) => {
    if (!soundOn) return;
    try {
      const ctx = getCtx();
      if (ctx.state === 'suspended') ctx.resume();
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = freq;
      osc.type = 'sine';
      gain.gain.setValueAtTime(volume, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + duration + 0.05);
    } catch {}
  }, [soundOn, getCtx]);

  // ── 이벤트별 사운드 ───────────────────────────────────────

  // 서행: 낮은 경고음 1회 / 정체: 높은 경보음 2회
  const playAlert = useCallback((level) => {
    if (level === 'SLOW') {
      playBeep(440, 0.4);
    } else if (level === 'CONGESTED' || level === 'JAM') {
      playBeep(880, 0.3);
      setTimeout(() => playBeep(880, 0.3), 420);
    }
  }, [playBeep]);

  // 이벤트 해소: 부드러운 안도음 2음계
  const playResolved = useCallback(() => {
    playBeep(523, 0.2, 0.3);   // C5
    setTimeout(() => playBeep(659, 0.3, 0.3), 220);  // E5
  }, [playBeep]);

  // 역주행: 고음 3연타 → 2.5초마다 반복 (버튼으로만 정지)
  const startWrongwayAlarm = useCallback(() => {
    if (wrongwayTimerRef.current) return;
    const alarm = () => {
      playBeep(1200, 0.15);
      setTimeout(() => playBeep(1200, 0.15), 200);
      setTimeout(() => playBeep(1200, 0.15), 400);
    };
    alarm();
    wrongwayTimerRef.current = setInterval(alarm, 2500);
  }, [playBeep]);

  const stopWrongwayAlarm = useCallback(() => {
    clearInterval(wrongwayTimerRef.current);
    wrongwayTimerRef.current = null;
  }, []);

  // 정체 5분 이상 지속: 30초마다 자동 반복 경보
  const startCongestionRepeat = useCallback(() => {
    if (congestionTimerRef.current) return;
    congestionTimerRef.current = setInterval(() => {
      playBeep(660, 0.3);
      setTimeout(() => playBeep(660, 0.3), 420);
    }, 30000);
  }, [playBeep]);

  const stopCongestionRepeat = useCallback(() => {
    clearInterval(congestionTimerRef.current);
    congestionTimerRef.current = null;
  }, []);

  // ── soundOn 토글 처리 ──────────────────────────────────────
  useEffect(() => {
    if (!ctxRef.current) return;
    if (soundOn) {
      ctxRef.current.resume();
    } else {
      ctxRef.current.suspend();
      stopWrongwayAlarm();
      stopCongestionRepeat();
    }
  }, [soundOn, stopWrongwayAlarm, stopCongestionRepeat]);

  // ── 언마운트 시 정리 ───────────────────────────────────────
  useEffect(() => {
    return () => {
      clearInterval(wrongwayTimerRef.current);
      clearInterval(congestionTimerRef.current);
      ctxRef.current?.close();
    };
  }, []);

  return {
    playAlert,
    playResolved,
    startWrongwayAlarm,
    stopWrongwayAlarm,
    startCongestionRepeat,
    stopCongestionRepeat,
  };
}
