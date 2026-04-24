/* eslint-disable */
// src/modules/monitoring/api.js
import axios from 'axios';

// localhost/127.0.0.1이면 http, 외부 호스트면 https 사용
const getProto = (host) =>
  (host.startsWith('localhost') || host.startsWith('127.')) ? 'http' : 'https';

// ✅ 헤더가 포함된 인스턴스 생성
const createClient = (host) => axios.create({
// <<<<<<< HEAD
//   baseURL: `${getProto(host)}://${host}/api/monitoring`,
// =======
  // baseURL: `https://${host}/api/monitoring`,
  baseURL: `http://${host}:5000/api/monitoring`,
// >>>>>>> 330c99599c04dd624521b83664f8ac057c3177e9
  headers: {
    'ngrok-skip-browser-warning': 'true'
  },
  timeout: 15000,   // 15초 후 자동으로 에러 발생 → catch 블록 실행 → 처리중 버튼 해제
});

export const startCamera = (host, params) =>
  createClient(host).post(`/start`, params);

export const stopCamera = (host, camera_id) =>
  createClient(host).post(`/stop`, { camera_id });

export const fetchCameras = (host) =>
  createClient(host).get(`/cameras`);

export const fetchDebug = (host, camera_id) =>
  createClient(host).get(`/debug/${camera_id}`);

export const fetchItsCctv = (host, road = 'gyeongbu') =>
  createClient(host).get(`/its/cctv`, { params: { road } });

export const fetchRoadGeo = (host, road = 'gyeongbu') =>
  createClient(host).get(`/its/road_geo`, { params: { road } });

export const startSegment = (host, road, start_ic, end_ic) =>
  createClient(host).post(`/its/start_segment`, { road, start_ic, end_ic });

export const stopSegment = (host, road, start_ic, end_ic) =>
  createClient(host).post(`/its/stop_segment`, { road, start_ic, end_ic });