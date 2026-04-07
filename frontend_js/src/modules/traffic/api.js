/* eslint-disable */
import axios from 'axios';

/**
 * 공공 CCTV 목록 및 스트리밍 URL 조회
 * AWS에서 ITS API 직접 호출이 차단되므로 브라우저에서 직접 호출 후 백엔드 캐시에 저장
 */
export const fetchCctvUrl = async (host) => {
  try {
    // 브라우저에서 ITS API 직접 호출 (AWS IP 차단 우회)
    const res = await axios.get('https://openapi.its.go.kr:9443/cctvInfo', {
      params: {
        apiKey: '22f088a782aa49f6a441b24c2b36d4ec',
        type: 'ex', cctvType: '1',
        minX: '126.8', maxX: '127.89',
        minY: '36.8',  maxY: '37.0', getType: 'json'
      }
    });

    const list = res.data.response?.data || [];
    const shuffled = [...list].sort(() => Math.random() - 0.5).slice(0, 4);
    const cctvData = shuffled.map(item => ({
      url: item.cctvurl, name: item.cctvname,
      lat: parseFloat(item.coordy), lng: parseFloat(item.coordx)
    }));

    // 백엔드 캐시에도 저장 (감지 시작 시 사용)
    await axios.post(`http://${host}:5000/api/its/set_cctv_list`, { cctvData });

    return { data: { success: true, cctvData } };

  } catch (e) {
    console.warn('ITS API 실패, 테스트 채널 사용:', e);
    const testUrl = 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8';
    const cctvData = Array.from({ length: 4 }, (_, i) => ({
      url: testUrl, name: `테스트 채널 ${i + 1}`, lat: 37.5, lng: 127.0
    }));
    return { data: { success: true, cctvData } };
  }
};

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