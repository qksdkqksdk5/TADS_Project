/* eslint-disable */
// src/modules/monitoring/api.js
// 백엔드 REST API를 호출하는 함수들을 모아놓은 파일
// 모든 요청은 createClient(host)가 만든 axios 인스턴스를 통해 전송된다
import axios from 'axios'; // HTTP 요청 라이브러리

// localhost 또는 127.0.0.1 이면 http, 외부 호스트이면 https 를 사용한다
// 이유: 로컬 개발 환경에서는 SSL 인증서가 없어 http가 필요하지만,
//       ngrok 등 외부 주소는 https 를 요구하기 때문
const getProto = (host) =>
  (host.startsWith('localhost') || host.startsWith('127.')) ? 'http' : 'https';

// ✅ 헤더가 포함된 axios 인스턴스를 생성한다
// host: 서버 주소 (예: "localhost:5000" 또는 "abc123.ngrok.io")
const createClient = (host) => axios.create({
// <<<<<<< HEAD
//   baseURL: `${getProto(host)}://${host}/api/monitoring`,
// =======
  // baseURL: `https://${host}/api/monitoring`,
  baseURL: `http://${host}:5000/api/monitoring`, // ⚠️ 병합 충돌 해결 필요 — 실제 사용할 URL로 정리해야 한다
// >>>>>>> 330c99599c04dd624521b83664f8ac057c3177e9
  headers: {
    'ngrok-skip-browser-warning': 'true' // ngrok 브라우저 경고 팝업을 API 요청에서 우회하기 위한 헤더
  },
  timeout: 15000, // 15초 안에 서버가 응답하지 않으면 자동으로 에러 발생 → catch 블록에서 "처리 중..." 버튼 해제
});

// 카메라 모니터링 시작 — params: { camera_id, rtsp_url 등 카메라 설정 }
export const startCamera = (host, params) =>
  createClient(host).post(`/start`, params);

// 카메라 모니터링 중지 — camera_id: 중지할 카메라의 고유 ID
export const stopCamera = (host, camera_id) =>
  createClient(host).post(`/stop`, { camera_id });

// 현재 등록된 카메라 전체 목록 조회
export const fetchCameras = (host) =>
  createClient(host).get(`/cameras`);

// 특정 카메라의 디버그 정보 조회 — 개발/문제 진단용
export const fetchDebug = (host, camera_id) =>
  createClient(host).get(`/debug/${camera_id}`);

// 지정한 고속도로의 ITS CCTV 목록과 IC 리스트 조회
// road: 고속도로 키 (예: 'gyeongbu', 'gyeongin' 등)
export const fetchItsCctv = (host, road = 'gyeongbu') =>
  createClient(host).get(`/its/cctv`, { params: { road } });

// 지정한 고속도로의 도로 형상(GeoJSON) 데이터 조회 — 지도 오버레이 표시에 사용
export const fetchRoadGeo = (host, road = 'gyeongbu') =>
  createClient(host).get(`/its/road_geo`, { params: { road } });

// 구간 모니터링 시작 — 시작/종료 IC 사이의 CCTV를 일괄 시작
// road: 고속도로 키, start_ic: 시작 IC명, end_ic: 종료 IC명
export const startSegment = (host, road, start_ic, end_ic) =>
  createClient(host).post(`/its/start_segment`, { road, start_ic, end_ic });

// 구간 모니터링 중지 — 시작/종료 IC 사이의 CCTV를 일괄 중지
export const stopSegment = (host, road, start_ic, end_ic) =>
  createClient(host).post(`/its/stop_segment`, { road, start_ic, end_ic });

// 연결 실패한 카메라를 최신 ITS URL로 강제 재시작한다.
// 백엔드가 기존 감지기를 중지하고 새 MonitoringDetector를 시작한다.
export const restartCamera = (host, camera_id) =>
  createClient(host).post(`/restart_camera`, { camera_id });
