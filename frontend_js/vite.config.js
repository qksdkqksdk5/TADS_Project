import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { createHtmlPlugin } from 'vite-plugin-html'

export default defineConfig(({ mode }) => {
  // 상위 폴더(../)에 있는 .env 파일을 읽어옵니다.
  const env = loadEnv(mode, '../');

  return {
    plugins: [
      react(),
      createHtmlPlugin({
        inject: {
          data: {
            // index.html의 %VITE_KAKAO_MAP_API_KEY%를 실제 값으로 치환합니다.
            VITE_KAKAO_MAP_API_KEY: env.VITE_KAKAO_MAP_API_KEY,
          },
        },
      }),
    ],
    envDir: '../',
    server: {
      host: '0.0.0.0',
      port: 5173,
      cors: true,
      allowedHosts: ['.ts.net']
    }
  }
})