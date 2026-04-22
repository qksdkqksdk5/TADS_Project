import os
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

candidate_paths = [
    os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".env")),       # backend_flask/.env
    os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", "..", ".env")), # 프로젝트 루트/.env
]

loaded_env_path = None
for env_path in candidate_paths:
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
        loaded_env_path = env_path
        break

print("📄 tunnel env loaded:", loaded_env_path)
print("ITS API URL = https://openapi.its.go.kr:9443/cctvInfo")
print("ITS_API_KEY exists =", bool(os.getenv("ITS_API_KEY")))


def get_its_tunnel_cctv_list():
    api_url = "https://openapi.its.go.kr:9443/cctvInfo"
    api_key = os.getenv("ITS_API_KEY", "").strip()

    if not api_key:
        print("❌ ITS_API_KEY 환경변수 없음")
        return []

    params = {
        "apiKey": api_key,
        "type": "ex",
        "cctvType": "1",
        "minX": "126.0",
        "maxX": "129.9",
        "minY": "34.0",
        "maxY": "38.9",
        "getType": "xml",
    }

    try:
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        print("✅ ITS 응답코드:", response.status_code)
        print("✅ ITS 응답 앞부분:", response.text[:1000])
    except Exception as e:
        print(f"❌ ITS API 호출 실패: {e}")
        return []

    try:
        root = ET.fromstring(response.text)
        print("✅ XML 루트 태그:", root.tag)
    except Exception as e:
        print(f"❌ ITS XML 파싱 실패: {e}")
        return []

    data_items = root.findall(".//data")
    print("✅ data 개수:", len(data_items))

    cctvs = []

    for item in data_items:
        name_tag = item.find("cctvname")
        url_tag = item.find("cctvurl")

        name = (name_tag.text or "").strip() if name_tag is not None else ""
        url = (url_tag.text or "").strip() if url_tag is not None else ""

        if name:
            print("📌 CCTV 이름:", name)

        if not name or not url:
            continue

        if "터널" in name:
            cctvs.append({
                "name": name,
                "url": url
            })

    print(f"✅ 필터 후 터널 CCTV 개수: {len(cctvs)}")
    return cctvs