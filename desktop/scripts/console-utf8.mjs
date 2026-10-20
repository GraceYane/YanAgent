import { spawnSync } from 'node:child_process'

// 在 Windows 上统一 Python 与 Electron 开发日志的编码。
if (process.platform === 'win32') {
  const result = spawnSync(
    process.env.ComSpec || 'cmd.exe',
    ['/d', '/c', 'chcp', '65001'],
    { stdio: 'ignore' },
  )

  if (result.error || result.status !== 0) {
    console.warn('[桌面端] 无法将 Windows 控制台切换为 UTF-8，日志可能出现乱码。')
  }
}
