/* eslint-disable */
import axios from 'axios';

/**
 * 공공 CCTV 목록 및 스트리밍 URL 조회
 * AWS에서 ITS API 직접 호출이 차단되므로 브라우저에서 직접 호출 후 백엔드 캐시에 저장
 */
// export const fetchCctvUrl = async (host) => {
//   try {
//     // 1. 백엔드에 이미 캐시된 데이터가 있는지 확인 (우선순위 1)
//     const checkRes = await axios.get(`http://${host}:5000/api/its/get_cctv_url`);
//     if (checkRes.data.success && checkRes.data.cctvData.length > 0) {
//       return { data: checkRes.data };
//     }

//     // 2. 캐시가 비어있을 때만 브라우저에서 직접 ITS API 호출 (최초 1회 실행용)
//     const res = await axios.get('https://openapi.its.go.kr:9443/cctvInfo', {
//       params: {
//         apiKey: '9241caeb859d43b0aaadf26b6b64988a',
//         type: 'ex', cctvType: '1',
//         minX: '126.8', maxX: '127.89',
//         minY: '36.8', maxY: '37.0', getType: 'json'
//       }
//     });

//     const list = res.data.response?.data || [];
//     const shuffled = [...list].sort(() => Math.random() - 0.5).slice(0, 4);
//     const cctvData = shuffled.map(item => ({
//       url: item.cctvurl, name: item.cctvname,
//       lat: parseFloat(item.coordy), lng: parseFloat(item.coordx)
//     }));

//     // 3. 백엔드 캐시에 저장 (이후 모든 사용자가 이 데이터를 공유)
//     await axios.post(`http://${host}:5000/api/its/set_cctv_list`, { cctvData });

//     return { data: { success: true, cctvData } };

//   } catch (e) {
//     console.warn('ITS API 실패, 테스트 채널 사용:', e);
//     const testUrl = 'https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8';
//     const cctvData = Array.from({ length: 4 }, (_, i) => ({
//       url: testUrl, name: `테스트 채널 ${i + 1}`, lat: 37.5, lng: 127.0
//     }));
//     return { data: { success: true, cctvData } };
//   }
// };

/**
 * 환경(호스트명)에 따라 API Base URL을 자동으로 결정하는 헬퍼 함수
 */
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
 * 공공 CCTV 목록 및 스트리밍 URL 조회
 */
  export const fetchCctvUrl = async (host, force = false) => {
    try {
      // 2. force가 true일 때만 URL 뒤에 ?force=true를 붙여줍니다.
      const url = `${getBaseUrl(host)}/its/get_cctv_url${force ? '?force=true' : ''}`;
      const res = await axios.get(url);
      
      if (res.data.success) {
        return { data: res.data };
      }
      throw new Error("데이터 로드 실패");

    } catch (e) {
      console.warn('CCTV 데이터 획득 실패 (Fallback 데이터 반환):', e);
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
  axios.post(`${getBaseUrl(host)}/start_simulation`, { type });

/**
 * 수동 캡처 요청
 * @param {string} type - 'sim' | 'webcam'
 * @param {string} adminName - 관리자 이름
 */
export const captureNow = (host, type, adminName) =>
  axios.post(`${getBaseUrl(host)}/capture_now`, { type, adminName });

/**
 * 캡처 메모 업데이트
 * @param {number} db_id
 * @param {string} memo
 */
export const updateCaptureMemo = (host, db_id, memo) =>
  axios.post(`${getBaseUrl(host)}/update_capture_memo`, { db_id, memo });

// ✅ 감지 시작 (스트리밍 없이 백그라운드 감지만)
export const startDetection = (host, { url, name, lat, lng, type }) =>
  axios.post(`${getBaseUrl(host)}/its/start_detection`, { url, name, lat, lng, type });

// ✅ 감지 중지
export const stopDetection = (host, { name, type }) =>
  axios.post(`${getBaseUrl(host)}/its/stop_detection`, { name, type });

// ✅ 감지 상태 확인
export const getDetectionStatus = (host) =>
  axios.get(`${getBaseUrl(host)}/its/detection_status`);

// ✅ 시뮬레이션 중지 요청 추가
export const stopSimulation = (host) =>
  axios.post(`${getBaseUrl(host)}/stop_simulation`).catch(() => {});