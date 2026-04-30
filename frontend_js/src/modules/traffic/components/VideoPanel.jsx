/* eslint-disable */
import React, { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import Swal from 'sweetalert2';
import { captureNow, updateCaptureMemo, stopDetection, getDetectionStatus, fetchCctvUrl } from '../api';

const getOrigin = (host) => {
  if (host.startsWith('http')) return host;
  const outsideHost = 'itsras.illit.kr';
  return host === outsideHost ? `https://${host}` : `http://${host}:5000`;
};

const SingleMedia = ({ url, isHls, name, isFlashing, onToggle, isOn, showToggle, customStyle, onRefreshUrl}) => {
  const videoRef = useRef(null);
  const hlsRef   = useRef(null);

  useEffect(() => {
    if (isHls && url && videoRef.current) {

      if (!hlsRef.current) {
        const hls = new Hls({
          fragLoadingMaxRetry: 10,
          manifestLoadingMaxRetry: 10,
          levelLoadingMaxRetry: 10,
          fragLoadingRetryDelay: 1000,
          manifestLoadingRetryDelay: 1000,
        });

        hls.attachMedia(videoRef.current);

        hls.on(Hls.Events.ERROR, (event, data) => {
          if (data.fatal) {
            switch (data.type) {
              case Hls.ErrorTypes.NETWORK_ERROR:
                if (
                  data.response?.code === 403 ||
                  data.response?.code === 401 ||
                  data.details === 'manifestLoadError'
                ) {
                  onRefreshUrl && onRefreshUrl();
                } else {
                  hls.startLoad();
                }
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

      // 🔥 source만 교체
      hlsRef.current.loadSource(url);
    }
    return () => { if (hlsRef.current) hlsRef.current.destroy(); };
  }, [url, isHls, onRefreshUrl]); // dependency에 onRefreshUrl 추가

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

const VideoPanel = ({ videoUrl, activeTab, cctvData = [], setCctvData, host, user }) => {
  const isCctvMode = activeTab === "cctv";
  const [isFlashing,    setIsFlashing]    = useState(false);
  const [expandedMedia, setExpandedMedia] = useState(null);
  const [reverseOn,     setReverseOn]     = useState(false);
  const [fireOn,        setFireOn]        = useState(false);

  useEffect(() => {
    if (!isCctvMode) return;

    console.log("🟢 CCTV 모드 → 자동 URL 갱신 시작");

    const interval = setInterval(() => {
      handleUrlRefresh();
    }, 60000); // 60초

    return () => {
      console.log("🔴 CCTV 모드 종료 → 갱신 중지");
      clearInterval(interval);
    };
  }, [activeTab]);

  const didInitRef = useRef(false);

  // cctv 탭 최초 진입 시 1회만 백엔드 상태 동기화
  useEffect(() => {
    if (!isCctvMode) {
      // cctv 탭이 아닐 때는 상태 초기화 + ref 리셋
      setReverseOn(false);
      setFireOn(false);
      didInitRef.current = false;
      return;
    }

    // cctv 탭인데 이미 초기화했으면 스킵 (cctvData URL 갱신으로 재실행돼도 무시)
    if (didInitRef.current) return;

    // cctvData가 아직 안 왔으면 대기
    if (cctvData.length === 0) return;

    didInitRef.current = true;

    getDetectionStatus(host).then(res => {
      const active = res.data.active || [];
      setReverseOn(active.some(name => name.includes('_reverse') && !name.includes('sim')));
      setFireOn(active.some(name => name.includes('_fire') && !name.includes('sim')));
    }).catch(() => {
      setReverseOn(false);
      setFireOn(false);
    });
  }, [isCctvMode, cctvData]); // activeTab 의존성 제거

  const handleToggle = async (type, currentOn, setOn) => {
    const idx = type === 'reverse' ? 0 : 1;
    const item = cctvData[idx];
    if (!item) return;

    if (currentOn) {
      setOn(false);
      try {
        await stopDetection(host, { name: item.name, type });
        await new Promise(res => setTimeout(res, 500));
      } catch {}
    } else {
      console.log(`🚀 ${item.name} 분석 시작 시도...`);
      try {
        // 백엔드에 감지기 생성 요청
        const origin = getOrigin(host);
        await fetch(`${origin}/api/its/start_detection`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url:  item.url,
            name: item.name,
            lat:  item.lat,
            lng:  item.lng,
            type
          })
        });
      } catch (err) {
        console.error('감지 시작 실패:', err);
      }
      setOn(true);
    }
  };

  const handleCapture = async () => {
    try {
      const res = await captureNow(host, activeTab, user?.name || '관리자');
      const { db_id, image_url } = res.data;
      const { value: text, isConfirmed } = await Swal.fire({
        title: '장면 캡처 완료', text: '기록할 메모가 있나요?', input: 'text',
        imageUrl: `${getOrigin(host)}${image_url}`,
        imageWidth: 300,
        showCancelButton: true, confirmButtonText: '메모 저장', cancelButtonText: '사진만 저장'
      });
      if (isConfirmed && text) await updateCaptureMemo(host, db_id, text);
    } catch (err) { console.error("캡처 오류:", err); }
  };

  // 1. URL 갱신 함수 추가
  const handleUrlRefresh = async () => {
    console.log("🔄 CCTV 토큰 만료 감지: 전체 URL 갱신 시도...");
    try {
      const response = await fetchCctvUrl(host, true); // force=true 전달
      if (response.data.success) {
        // 부모인 TrafficModule 등에서 내려준 setCctvData가 있다면 호출
        // (만약 props에 없다면 VideoPanel 내부 state로 관리하도록 수정 필요)
        setCctvData(response.data.cctvData); 
      }
    } catch (err) {
      console.error("URL 갱신 실패:", err);
    }
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
                finalUrl = `${getOrigin(host)}/api/its/video_feed?url=${encodeURIComponent(item.url)}&name=${encodeURIComponent(item.name)}&lat=${item.lat}&lng=${item.lng}`;
                
                isHls    = false;
              } else if (isFire && fireOn) {
                finalUrl = `${getOrigin(host)}/api/its/fire_feed?url=${encodeURIComponent(item.url)}&name=${encodeURIComponent(item.name)}&lat=${item.lat}&lng=${item.lng}`;
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
                    key={idx}
                    url={finalUrl} isHls={isHls} name={displayName}
                    showToggle={isReverse || isFire}
                    isOn={isOn}
                    onToggle={() => isReverse
                      ? handleToggle('reverse', reverseOn, setReverseOn)
                      : handleToggle('fire', fireOn, setFireOn)
                    }
                    onRefreshUrl={handleUrlRefresh}
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