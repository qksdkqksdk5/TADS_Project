/* eslint-disable */
// src/modules/plate/index.jsx
import { useState, useEffect, useRef } from 'react';
import { plateApi } from './api';
import ControlBox      from './components/ControlBox';
import VideoStream     from './components/VideoStream';
import PlateList       from './components/PlateList';
import AnalyticsModal  from './components/AnalyticsModal';

export default function PlateModule({ host }) {
  const BASE_URL = `http://${host || window.location.hostname}:5000/api/plate`;
  const api = plateApi(BASE_URL);

  const [connected, setConnected]                 = useState(false);
  const [started, setStarted]                     = useState(false);
  const [videos, setVideos]                       = useState([]);
  const [preprocessMethods, setPreprocessMethods] = useState([]);
  const [plates, setPlates]                       = useState([]);
  const [allResults, setAllResults]               = useState([]);
  const [resultVideos, setResultVideos]           = useState([]);
  const [videoFilter, setVideoFilter]             = useState('');
  const [showAnalytics, setShowAnalytics]         = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    api.health()
      .then(() => {
        setConnected(true);
        return Promise.all([api.getVideos(), api.getPreprocessMethods()]);
      })
      .then(([videosRes, methodsRes]) => {
        setVideos(videosRes.data.videos || []);
        setPreprocessMethods(methodsRes.data.methods || []);
      })
      .catch(() => setConnected(false));
  }, []);

  // 폴링 — started 이후
  useEffect(() => {
    if (!started) return;
    pollRef.current = setInterval(async () => {
      try {
        const [platesRes, resultsRes] = await Promise.all([
          api.getPlates(),
          api.getResults(videoFilter),
        ]);
        setPlates(platesRes.data);
        setAllResults(resultsRes.data.results || []);
        setResultVideos(resultsRes.data.videos || []);
      } catch {}
    }, 1000);
    return () => clearInterval(pollRef.current);
  }, [started, videoFilter]);

  // 연결되면 즉시 전체기록 로드 (CSV 복원)
  useEffect(() => {
    if (!connected) return;
    api.getResults().then(res => {
      setAllResults(res.data.results || []);
      setResultVideos(res.data.videos || []);
    }).catch(() => {});
  }, [connected]);

  const handleStart = async (video) => {
    await api.start(video);
    setStarted(true);
  };

  // 필터 변경 시 즉시 API 호출
  const handleVideoFilter = async (video) => {
    setVideoFilter(video);
    try {
      const res = await api.getResults(video);
      setAllResults(res.data.results || []);
      setResultVideos(res.data.videos || []);
    } catch {}
  };

  const handleVerify = async (id, groundTruth) => {
    const res = await api.verify(id, groundTruth);
    setAllResults(prev => prev.map(r =>
      r.id === id ? { ...r, ...res.data, ground_truth: groundTruth } : r
    ));
  };

  const handleReprocess = async (id, preprocess) => {
    const res = await api.reprocess(id, preprocess);
    setAllResults(prev => prev.map(r =>
      r.id === id ? { ...r, preprocess_results: res.data.preprocess_results } : r
    ));
  };

  return (
    <div style={s.container}>
      <div style={s.body}>
        <div style={s.left}>
          <ControlBox
            connected={connected}
            videos={videos}
            onStart={handleStart}
            onAnalytics={() => setShowAnalytics(true)}
          />
          <VideoStream
            started={started}
            streamUrl={`${BASE_URL}/stream`}
          />
        </div>
        <PlateList
          plates={plates}
          allResults={allResults}
          resultVideos={resultVideos}
          videoFilter={videoFilter}
          onVideoFilter={handleVideoFilter}
          baseUrl={`http://${host || window.location.hostname}:5000`}
          preprocessMethods={preprocessMethods}
          onVerify={handleVerify}
          onReprocess={handleReprocess}
        />
      </div>

      {showAnalytics && (
        <AnalyticsModal
          baseUrl={BASE_URL}
          onClose={() => setShowAnalytics(false)}
        />
      )}
    </div>
  );
}

const s = {
  container: {
    flex: 1, height: '100%', background: '#0f0f1a',
    color: '#e0e0ff', display: 'flex', flexDirection: 'column',
    padding: '15px', boxSizing: 'border-box', overflow: 'hidden',
  },
  body: { display: 'flex', gap: '20px', flex: 1, minHeight: 0 },
  left: { flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', minHeight: 0 },
};