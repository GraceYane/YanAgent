import { spawnSync } from 'node:child_process'

// Keep Python and Electron development logs on the same encoding on Windows.
if (process.platform === 'win32') {
  const result = spawnSync(
    process.env.ComSpec || 'cmd.exe',
    ['/d', '/c', 'chcp', '65001'],
    { stdio: 'ignore' },
  )

  if (result.error || result.status !== 0) {
    console.warn('[desktop] Unable to switch the Windows console to UTF-8; logs may be garbled.')
  }
}
