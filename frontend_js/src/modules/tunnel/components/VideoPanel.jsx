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
