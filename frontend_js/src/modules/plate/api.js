// src/modules/plate/api.js
// plate 모듈 API 호출 모음
// BASE_URL은 호출 시 주입

import axios from 'axios';

export const plateApi = (baseUrl) => ({

  health: () =>
    axios.get(`${baseUrl}/health`),

  getVideos: () =>
    axios.get(`${baseUrl}/videos`),

  getPreprocessMethods: () =>
    axios.get(`${baseUrl}/preprocess_methods`),

  start: (video) =>
    axios.post(`${baseUrl}/start`, { video }),

  getPlates: () =>
    axios.get(`${baseUrl}/plates`),

  getResults: (video = '') =>
    axios.get(`${baseUrl}/results${video ? `?video=${video}` : ''}`),

  verify: (id, groundTruth) =>
    axios.post(`${baseUrl}/verify`, { id, ground_truth: groundTruth }),

  reprocess: (id, preprocess) =>
    axios.post(`${baseUrl}/reprocess`, { id, preprocess }),

  init: () => 
    axios.get(`${baseUrl}/init`),

});