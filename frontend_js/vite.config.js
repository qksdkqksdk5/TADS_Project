import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { createHtmlPlugin } from 'vite-plugin-html'

export default defineConfig(({ mode }) => {
  /**
   * 1. 환경 변수 로드 (이중 체크)
   * - envDocker: 도커 빌드 시 주입된 시스템 환경 변수를 읽어옴
   * - envLocal: 로컬 개발 시 상위 폴더(../)의 .env 파일을 읽어옴
   */
  const envDocker = loadEnv(mode, process.cwd(), ''); 
  const envLocal = loadEnv(mode, '../', '');

  // 두 곳 중 하나라도 키가 있으면 가져옵니다.
  const KAKAO_KEY = envDocker.VITE_KAKAO_MAP_API_KEY || envLocal.VITE_KAKAO_MAP_API_KEY;

  return {
    plugins: [
      react(),
      createHtmlPlugin({
        inject: {
          data: {
            // index.html의 %VITE_KAKAO_MAP_API_KEY%를 치환
            VITE_KAKAO_MAP_API_KEY: KAKAO_KEY,
          },
        },
      }),
    ],
    server: {
      host: '0.0.0.0',
      port: 5173,
      cors: true,
      allowedHosts: ['.ts.net']
    },
    build: {
      outDir: 'dist',
    }
  }
})