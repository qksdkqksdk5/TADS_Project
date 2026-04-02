/* eslint-disable */
import axios from 'axios';

/**
 * 공공 CCTV 목록 및 스트리밍 URL 조회
 */
export const fetchCctvUrl = (host) =>
  axios.get(`http://${host}:5000/api/its/get_cctv_url`);

/**
 * 시뮬레이션 시작 요청
 * @param {string} type - 'sim' | 'webcam'
 */
export const startSimulation = (host, type) =>
  axios.post(`http://${host}:5000/api/start_simulation`, { type });

/**
 * 수동 캡처 요청
 * @param {string} type - 'sim' | 'webcam'
 * @param {string} adminName - 관리자 이름
 */
export const captureNow = (host, type, adminName) =>
  axios.post(`http://${host}:5000/api/capture_now`, { type, adminName });

/**
 * 캡처 메모 업데이트
 * @param {number} db_id
 * @param {string} memo
 */
export const updateCaptureMemo = (host, db_id, memo) =>
  axios.post(`http://${host}:5000/api/update_capture_memo`, { db_id, memo });

// ✅ 감지 시작 (스트리밍 없이 백그라운드 감지만)
export const startDetection = (host, { url, name, lat, lng, type }) =>
  axios.post(`http://${host}:5000/api/its/start_detection`, { url, name, lat, lng, type });
 
// ✅ 감지 중지
export const stopDetection = (host, { name, type }) =>
  axios.post(`http://${host}:5000/api/its/stop_detection`, { name, type });
 
// ✅ 감지 상태 확인
export const getDetectionStatus = (host) =>
  axios.get(`http://${host}:5000/api/its/detection_status`);
