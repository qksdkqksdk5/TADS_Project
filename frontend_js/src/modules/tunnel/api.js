import axios from "axios";

/* =========================================================
 * tunnel status
 * ========================================================= */
export const fetchTunnelStatus = async (BACKEND_URL) => {
  const res = await axios.get(`${BACKEND_URL}/api/tunnel/status`);
  return res.data;
};

/* =========================================================
 * CCTV 리스트 저장
 * ========================================================= */
export const setTunnelCctvList = async (BACKEND_URL, items) => {
  const res = await axios.post(`${BACKEND_URL}/api/tunnel/set-cctv-list`, {
    items,
  });
  return res.data;
};

/* =========================================================
 * CCTV 리스트 조회
 * ========================================================= */
export const getTunnelCctvList = async (BACKEND_URL) => {
  const res = await axios.get(`${BACKEND_URL}/api/tunnel/cctv-list`);
  return res.data;
};

/* =========================================================
 * 랜덤 CCTV 선택
 * ========================================================= */
export const selectRandomCctv = async (BACKEND_URL) => {
  const res = await axios.get(`${BACKEND_URL}/api/tunnel/select-random`);
  return res.data;
};

/* =========================================================
 * 이름으로 CCTV 선택
 * ========================================================= */
export const selectCctvByName = async (BACKEND_URL, name) => {
  const res = await axios.get(`${BACKEND_URL}/api/tunnel/select-cctv`, {
    params: { name },
  });
  return res.data;
};

/* =========================================================
 * ITS OpenAPI 기반 최신 CCTV 목록 조회
 * - 먼저 백엔드 캐시를 확인
 * - 없으면 브라우저에서 ITS API 직접 조회 후
 *   tunnel 모듈 형식에 맞게 변환해서 반환
 * ========================================================= */
export const fetchTunnelCctvUrl = async (host) => {
  try {
    const BACKEND_URL = `http://${host}:5000`;

    // 1) 백엔드 캐시 우선 확인
    const cachedRes = await getTunnelCctvList(BACKEND_URL);
    if (cachedRes?.ok && Array.isArray(cachedRes?.items) && cachedRes.items.length > 0) {
      return {
        ok: true,
        items: cachedRes.items,
        source: "cache",
      };
    }

    // 2) 캐시가 없으면 ITS API 직접 조회
    const res = await axios.get("https://openapi.its.go.kr:9443/cctvInfo", {
      params: {
        apiKey: "9241caeb859d43b0aaadf26b6b64988a",
        type: "ex",
        cctvType: "1",
        minX: "126.8",
        maxX: "127.89",
        minY: "36.8",
        maxY: "37.9",
        getType: "json",
      },
      timeout: 10000,
    });

    const list = res?.data?.response?.data || [];

    // 이름에 "터널"이 포함된 CCTV만 우선 사용
    const tunnelOnly = list.filter((item) =>
      String(item?.cctvname || "").includes("터널")
    );

    // 너무 많으면 일부만 사용
    const picked = (tunnelOnly.length > 0 ? tunnelOnly : list)
      .sort(() => Math.random() - 0.5)
      .slice(0, 8);

    const items = picked
      .map((item) => ({
        name: item?.cctvname || "터널 CCTV",
        url: item?.cctvurl || "",
      }))
      .filter((item) => item.name && item.url);

    if (items.length === 0) {
      throw new Error("ITS API에서 유효한 CCTV URL을 찾지 못했습니다.");
    }

    // 3) 백엔드 캐시에 저장
    await setTunnelCctvList(BACKEND_URL, items);

    return {
      ok: true,
      items,
      source: "its_api",
    };
  } catch (e) {
    console.warn("터널 ITS API 실패, fallback 사용:", e);

    // fallback 테스트용 리스트
    const fallbackItems = [
      {
        name: "테스트 채널 1",
        url: "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
      },
      {
        name: "테스트 채널 2",
        url: "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
      },
      {
        name: "테스트 채널 3",
        url: "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
      },
      {
        name: "테스트 채널 4",
        url: "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
      },
    ];

    return {
      ok: true,
      items: fallbackItems,
      source: "fallback",
    };
  }
};