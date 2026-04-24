/* eslint-disable */
import React, { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import Swal from 'sweetalert2';
import { captureNow, updateCaptureMemo, stopDetection, getDetectionStatus } from '../api';

const SingleMedia = ({ url, isHls, name, isFlashing, onToggle, isOn, showToggle, customStyle }) => {
  const videoRef = useRef(null);
  const hlsRef   = useRef(null);

  useEffect(() => {
    if (isHls && url && videoRef.current) {
      if (hlsRef.current) hlsRef.current.destroy();

      if (videoRef.current.canPlayType('application/vnd.apple.mpegurl')) {
        videoRef.current.src = url;
      } else if (Hls.isSupported()) {
        const hls = new Hls({
          fragLoadingMaxRetry:      10,
          manifestLoadingMaxRetry:  10,
          levelLoadingMaxRetry:     10,
          fragLoadingRetryDelay:    1000,
          manifestLoadingRetryDelay: 1000,
        });
        hls.loadSource(url);
        hls.attachMedia(videoRef.current);
        hls.on(Hls.Events.ERROR, (event, data) => {
          if (data.fatal) {
            switch (data.type) {
              case Hls.ErrorTypes.NETWORK_ERROR:
                console.log("🌐 네트워크 에러 발생 - URL 갱신 시도");
                // 부모 컴포넌트(VideoPanel)로부터 전달받은 갱신 함수 호출
                onRefreshUrl(); 
                break;
              case Hls.ErrorTypes.MEDIA_ERROR:
                hls.recoverMediaError();
                break;
              default:
                hls.destroy();
                break;
            }
          }
        });
        hlsRef.current = hls;
      }
    }
    return () => { if (hlsRef.current) hlsRef.current.destroy(); };
  }, [url, isHls]);

  return (
    <div style={gridItemStyle}>
      {isHls ? (
        <video ref={videoRef} autoPlay muted playsInline style={{ ...mediaStyle, ...customStyle }} />
      ) : (
        <img
          src={url}
          style={{ ...mediaStyle, ...customStyle, filter: isFlashing ? 'brightness(2.5)' : 'none', transition: 'filter 0.15s ease' }}
          alt="streaming"
        />
      )}
      <div style={miniLabelStyle}>{name}</div>

      {/* ✅ 각 영상 우상단 토글 버튼 */}
      {showToggle && (
        <button
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          style={{ ...inlineToggleStyle, background: isOn ? 'rgba(220,38,38,0.85)' : 'rgba(15,23,42,0.7)', borderColor: isOn ? '#ef4444' : '#475569' }}
        >
          {isOn ? '● AI ON' : '○ AI OFF'}
        </button>
      )}
    </div>
  );
};

const VideoPanel = ({ videoUrl, activeTab, cctvData = [], host, user }) => {
  const isCctvMode = activeTab === "cctv";
  const [isFlashing,    setIsFlashing]    = useState(false);
  const [expandedMedia, setExpandedMedia] = useState(null);
  const [reverseOn,     setReverseOn]     = useState(false);
  const [fireOn,        setFireOn]        = useState(false);

  // ✅ 새로고침 후 백엔드 detector 상태와 UI 동기화
  useEffect(() => {
    if (cctvData.length > 0) {
      getDetectionStatus(host).then(res => {
        const active = res.data.active || [];
        setReverseOn(active.some(name => name.includes('_reverse') && !name.includes('sim')));
        setFireOn(active.some(name => name.includes('_fire') && !name.includes('sim')));
      }).catch(() => {});
    }
  }, [cctvData]);

  useEffect(() => {
    return () => {
      setReverseOn(false);
      setFireOn(false);
    };
  }, [activeTab]);

  const handleToggle = async (type, currentOn, setOn) => {
    const idx = type === 'reverse' ? 0 : 1;
    const item = cctvData[idx];
    if (!item) return;

    if (currentOn) {
      setOn(false);
      try { await stopDetection(host, { name: item.name, type }); } catch {}
    } else {
      // 🟢 AI ON 시
      console.log(`🚀 ${item.name} 분석 시작 시도...`);
      
      // 1. 백엔드에게 "주소가 죽었을 수 있으니 최신 주소로 갱신해줘"라고 요청 (옵션)
      // 혹은 단순히 딜레이를 주어 브라우저 소켓 해제 대기
      await new Promise(resolve => setTimeout(resolve, 800)); 
      
      // 2. ON으로 변경 (이때 video_feed 라우트가 호출됨)
      setOn(true);
    }
  };

  const handleCapture = async () => {
    try {
      const res = await captureNow(host, activeTab, user?.name || '관리자');
      const { db_id, image_url } = res.data;
      const { value: text, isConfirmed } = await Swal.fire({
        title: '장면 캡처 완료', text: '기록할 메모가 있나요?', input: 'text',
        imageUrl: `http://${host}:5000${image_url}`, imageWidth: 300,
        showCancelButton: true, confirmButtonText: '메모 저장', cancelButtonText: '사진만 저장'
      });
      if (isConfirmed && text) await updateCaptureMemo(host, db_id, text);
    } catch (err) { console.error("캡처 오류:", err); }
  };

  return (
    <div style={containerStyle}>
      <div style={labelStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div style={{ width: '6px', height: '6px', background: '#ef4444', borderRadius: '50%' }} />
          {isCctvMode ? "고속도로 실시간 멀티 관제" : "LOCAL FEED"}
        </div>
        <div style={{ fontSize: '10px', opacity: 0.6 }}>{activeTab.toUpperCase()} MODE</div>
      </div>

      {isCctvMode ? (
        <div style={quadGridStyle}>
          {cctvData.length > 0 ? (
            cctvData.map((item, idx) => {
              const isReverse = idx === 0;
              const isFire    = idx === 1;
              const isOn      = isReverse ? reverseOn : (isFire ? fireOn : false);

              let finalUrl = item.url;
              let isHls    = true;

              if (isReverse && reverseOn) {
                finalUrl = `http://${host}:5000/api/its/video_feed?url=${encodeURIComponent(item.url)}&name=${encodeURIComponent(item.name)}&lat=${item.lat}&lng=${item.lng}`;
                isHls    = false;
              } else if (isFire && fireOn) {
                finalUrl = `http://${host}:5000/api/its/fire_feed?url=${encodeURIComponent(item.url)}&name=${encodeURIComponent(item.name)}&lat=${item.lat}&lng=${item.lng}`;
                isHls    = false;
              }
              const displayName = isReverse
                ? `🔴 ${item.name}`
                : isFire
                  ? `🔥 ${item.name}`
                  : item.name;

              return (
                <div key={idx} style={{ cursor: 'zoom-in', width: '100%', height: '100%' }}
                  onClick={() => setExpandedMedia({ url: finalUrl, isHls, name: item.name })}>
                  <SingleMedia
                    key={finalUrl}
                    url={finalUrl} isHls={isHls} name={displayName}
                    showToggle={isReverse || isFire}
                    isOn={isOn}
                    onToggle={() => isReverse
                      ? handleToggle('reverse', reverseOn, setReverseOn)
                      : handleToggle('fire', fireOn, setFireOn)
                    }
                  />
                </div>
              );
            })
          ) : (
            <div style={loadingStyle}>CCTV 데이터를 불러오는 중...</div>
          )}
        </div>
      ) : (
        <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
          {videoUrl ? (
            <>
              <SingleMedia url={videoUrl} isHls={false} isFlashing={isFlashing} />
              <button onClick={handleCapture} style={captureBtnStyle}
                onMouseEnter={(e) => e.target.style.transform = 'scale(1.1)'}
                onMouseLeave={(e) => e.target.style.transform = 'scale(1)'}
                title="현재 화면 수동 기록 및 메모">📷</button>
            </>
          ) : (
            <div style={loadingStyle}>연결 신호 대기 중...</div>
          )}
        </div>
      )}

      {expandedMedia && (
        <div style={modalOverlayStyle} onClick={() => setExpandedMedia(null)}>
          <div style={modalContentStyle} onClick={(e) => e.stopPropagation()}>
            <div style={{ position: 'relative', width: '95vw', height: '90vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#000', borderRadius: '8px', overflow: 'hidden' }}>
              <div style={{ width: '100%', height: '100%' }}>
                <SingleMedia url={expandedMedia.url} isHls={expandedMedia.isHls} name={expandedMedia.name} customStyle={{width: '100%', height: '90%', maxWidth: '100%', maxHeight: '100%', objectFit: 'contain'}}/>
              </div>
              <button style={closeBtnStyle} onClick={() => setExpandedMedia(null)}>✕ 닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const modalOverlayStyle  = { position: 'fixed', top: 100, left: 130, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.85)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(5px)', width: '90%', height: '80%' };
const modalContentStyle  = { padding: '5px', background: '#1e293b', borderRadius: '12px', borderWidth: '2px', borderStyle: 'solid', borderColor: '#334155', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' };
const closeBtnStyle      = { position: 'absolute', top: '10px', right: '10px', background: 'rgba(239,68,68,0.8)', color: 'white', border: 'none', padding: '8px 15px', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: 'bold', zIndex: 10 };
const containerStyle     = { height: '100%', background: '#000', position: 'relative', overflow: 'hidden' };
const quadGridStyle      = { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gridTemplateRows: 'repeat(2, minmax(0, 1fr))', width: '100%', height: '100%', gap: '4px', background: '#020617', boxSizing: 'border-box', overflow: 'hidden' };
const gridItemStyle      = { position: 'relative', width: '100%', height: '100%', background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', border: '1px solid #1e293b' };
const mediaStyle         = { maxWidth: '95%', maxHeight: '95%', width: '90%', height: '90%', objectFit: 'contain', display: 'block', boxShadow: '0 0 15px rgba(0,0,0,0.5)', borderRadius: '2px' };
const miniLabelStyle     = { position: 'absolute', bottom: '10px', left: '10px', background: 'rgba(15,23,42,0.75)', color: '#fff', padding: '3px 8px', fontSize: '11px', borderRadius: '4px', border: '1px solid rgba(99,102,241,0.3)', pointerEvents: 'none', zIndex: 5 };
const labelStyle         = { position: 'absolute', top: 0, left: 0, right: 0, padding: '10px 15px', background: 'linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%)', zIndex: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#fff', fontSize: '12px', fontWeight: 'bold', pointerEvents: 'none' };
const captureBtnStyle    = { position: 'absolute', right: '20px', bottom: '20px', width: '50px', height: '50px', borderRadius: '50%', backgroundColor: 'rgba(37,99,235,0.8)', border: '2px solid rgba(255,255,255,0.3)', color: 'white', fontSize: '22px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(4px)', transition: 'all 0.2s ease', zIndex: 10, boxShadow: '0 4px 15px rgba(0,0,0,0.5)' };
const loadingStyle       = { color: '#475569', fontSize: '13px' };
const inlineToggleStyle  = { position: 'absolute', top: '8px', right: '8px', color: 'white', border: '1px solid', padding: '3px 8px', borderRadius: '20px', fontSize: '10px', fontWeight: '600', cursor: 'pointer', zIndex: 6, backdropFilter: 'blur(4px)', transition: 'all 0.2s', letterSpacing: '0.3px' };

export default VideoPanel;