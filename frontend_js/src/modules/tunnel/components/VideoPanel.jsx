// ==========================================
// # 파일명: VideoPanel.jsx
// # 역할: CCTV 영상 출력만 담당

// 영상 URL, 로딩 상태, CCTV 이름, 연결 실패 처리 함수를 props로 받아 화면을 렌더링
// video-feed 경로는 index.jsx에서 만든 videoFeedUrl을 그대로 사용(백엔드 경로와 충돌방지)
//  
// # ==========================================


export default function VideoPanel({
  videoLoading,
  videoFeedUrl,
  status,
  lastSelectedCctv,
  cctvSourceText,
  onVideoLoad,
  onVideoError,
}) {
  const cctvName = status?.cctv_name || lastSelectedCctv?.name || "-";

  return (
    <div className="panel panel-video">
      <div className="section-title">📹 CCTV</div>

      <div className="video-wrap">
        {videoLoading && (
          <div className="video-overlay-message">
            <div>영상 연결 중입니다</div>
            <div className="video-overlay-sub">
              화면이 계속 나오지 않으면 영상새로고침을 눌러주세요
            </div>
          </div>
        )}

        {!videoLoading && !videoFeedUrl && (
          <div className="video-inactive-box">
            터널 탭 비활성화 또는 서비스 정지 상태
          </div>
        )}

        {videoFeedUrl && (
          <img
            key={videoFeedUrl}
            src={videoFeedUrl}
            alt="cctv"
            className="video-image"
            onLoad={onVideoLoad}
            onError={onVideoError}
          />
        )}
      </div>

      <div className="video-caption">{cctvName}</div>
      {cctvSourceText && <div className="video-debug-source">{cctvSourceText}</div>}
    </div>
  );
}
