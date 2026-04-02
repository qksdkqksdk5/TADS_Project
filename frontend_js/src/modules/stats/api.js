/* eslint-disable */
import axios from 'axios';

/**
 * 통계 요약 데이터 조회
 * @param {string} mode - 'real' | 'sim' | 'all'
 */
export const fetchStatsSummary = (host, mode) =>
  axios.get(`http://${host}:5000/api/stats/summary?mode=${mode}`);

/**
 * 상세 이력 데이터 조회
 * @param {string} date - 'YYYY-MM-DD'
 * @param {string} mode - 'real' | 'sim' | 'all'
 */
export const fetchStatsHistory = (host, date, mode) =>
  axios.get(`http://${host}:5000/api/stats/history?date=${date}&mode=${mode}`);
