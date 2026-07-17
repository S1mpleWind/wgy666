import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    // 服务器后端
    //'import.meta.env.VITE_API_BASE_URL': JSON.stringify('http://10.119.4.70:8000'),

    // 本地调试用：
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify('http://localhost:8000'),
  },
})
