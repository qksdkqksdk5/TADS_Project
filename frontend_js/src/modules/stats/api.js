/* eslint-disable */
import axios from 'axios';

const getBaseUrl = (host) => {
  // 이미 http/https가 포함된 전체 URL이 넘어온 경우 그대로 사용
  if (host.startsWith('http')) return host;

  const outsideHost = 'itsras.illit.kr';

  // 요청 호스트가 외부 도메인인 경우 무조건 HTTPS 적용
  if (host === outsideHost) {
    return `https://${host}/api`;
  }

  // 그 외 로컬(localhost)이나 내부망 IP 등인 경우 http + 5000 포트 적용
  return `http://${host}:5000/api`;
};

/**
 * 통계 요약 데이터 조회
 * @param {string} mode - 'real' | 'sim' | 'all'
 */
export const fetchStatsSummary = (host, mode) =>
  axios.get(`${getBaseUrl(host)}/stats/summary?mode=${mode}`);

/**
 * 상세 이력 데이터 조회
 * @param {string} date - 'YYYY-MM-DD'
 * @param {string} mode - 'real' | 'sim' | 'all'
 */
export const fetchStatsHistory = (host, date, mode) =>
  axios.get(`${getBaseUrl(host)}/stats/history?date=${date}&mode=${mode}`);
