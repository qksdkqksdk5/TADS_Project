/* eslint-disable */
// src/modules/monitoring/api.js
import axios from 'axios';

// ✅ 헤더가 포함된 인스턴스 생성
const createClient = (host) => axios.create({
  baseURL: `https://${host}/api/monitoring`,
  headers: {
    'ngrok-skip-browser-warning': 'true'
  }
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