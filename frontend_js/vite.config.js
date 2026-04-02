import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const rootPath = path.resolve(__dirname, '../');
  const env = loadEnv(mode, rootPath, '');

  const kakaoKey = env.VITE_KAKAO_MAP_API_KEY 
                || process.env.VITE_KAKAO_MAP_API_KEY 
                || "";

  return {
    server: {
      fs: { allow: [rootPath] },
      host: '0.0.0.0',
      port: 5173,
      cors: true,
      allowedHosts: ['.ts.net']
    },
    plugins: [react()],
    define: {
      __KAKAO_KEY__: JSON.stringify(kakaoKey)  // 빌드 시 번들에 값 직접 삽입
    }
  }
})