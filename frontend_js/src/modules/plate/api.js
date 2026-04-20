// src/modules/plate/api.js
import axios from 'axios';

export const plateApi = (baseUrl) => {
  const client = axios.create({
    baseURL: baseUrl,
    headers: {
      'ngrok-skip-browser-warning': 'true'
    }
  });

  return {
    health: () => client.get('/health'),
    getVideos: () => client.get('/videos'),
    getPreprocessMethods: () => client.get('/preprocess_methods'),
    start: (video, operatorName) => client.post('/start', { video, operator_name: operatorName }),
    getPlates: () => client.get('/plates'),
    getResults: (video = '') => client.get(`/results${video ? `?video=${video}` : ''}`),
    verify: (id, groundTruth) => client.post('/verify', { id, ground_truth: groundTruth }),
    reprocess: (id, preprocess) => client.post('/reprocess', { id, preprocess }),
    init: () => client.get('/init'),
    stop: () => client.post('/stop'),
  };
};