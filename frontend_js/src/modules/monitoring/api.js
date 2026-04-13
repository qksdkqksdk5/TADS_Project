/* eslint-disable */
// src/modules/monitoring/api.js
import axios from 'axios';

const base = (host) => `http://${host}:5000/api/monitoring`;

export const startCamera = (host, params) =>
  axios.post(`${base(host)}/start`, params);

export const stopCamera = (host, camera_id) =>
  axios.post(`${base(host)}/stop`, { camera_id });

export const fetchCameras = (host) =>
  axios.get(`${base(host)}/cameras`);

export const fetchDebug = (host, camera_id) =>
  axios.get(`${base(host)}/debug/${camera_id}`);

// ── ITS 연동 API ──────────────────────────────────────────────

/** 고속도로별 ITS CCTV 목록 + IC 리스트 조회 */
export const fetchItsCctv = (host, road = 'gyeongbu') =>
  axios.get(`${base(host)}/its/cctv`, { params: { road } });

/** Overpass OSM 도로 선형 GeoJSON 조회 */
export const fetchRoadGeo = (host, road = 'gyeongbu') =>
  axios.get(`${base(host)}/its/road_geo`, { params: { road } });

/** IC 범위 내 CCTV MonitoringDetector 일괄 시작 */
export const startSegment = (host, road, start_ic, end_ic) =>
  axios.post(`${base(host)}/its/start_segment`, { road, start_ic, end_ic });

/** IC 범위 내 MonitoringDetector 일괄 중지 */
export const stopSegment = (host, road, start_ic, end_ic) =>
  axios.post(`${base(host)}/its/stop_segment`, { road, start_ic, end_ic });
