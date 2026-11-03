import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const electronPath = require('electron')
const port = process.env.YANAGENT_EXTERNAL_BACKEND_PORT?.trim() || '9876'

console.log(`[桌面端] 连接 IDE 外部后端：http://127.0.0.1:${port}`)

const electron = spawn(electronPath, ['.'], {
  cwd: process.cwd(),
  env: {
    ...process.env,
    YANAGENT_EXTERNAL_BACKEND_PORT: port,
  },
  stdio: 'inherit',
})

electron.on('error', (error) => {
  console.error(`[桌面端] Electron 启动失败：${error.message}`)
  process.exitCode = 1
})

electron.on('exit', (code, signal) => {
  if (signal) {
    console.log(`[桌面端] Electron 已结束：${signal}`)
  }
  process.exitCode = code ?? 0
})
