import React, { useState } from 'react'
import apiClient from '../api/client'
import { t } from '../i18n'
import { sessionOwner } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import type { RunDiagnostics as Diagnostics } from '../types'

/** 展示持久化的任务诊断，并通过显式动作继续或安全重试。 */
export default function RunDiagnostics({ sessionId, requestId }: { sessionId: string; requestId: string }) {
  const [data, setData] = useState<Diagnostics | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const recover = useChatStore((s) => s.recover)
  const isStreaming = useChatStore((s) => s.sessions[sessionId]?.isStreaming ?? false)

  /** 每次展开重新查询，避免以过期的任务状态提供恢复操作。 */
  const load = async () => {
    setError('')
    try {
      setData(await apiClient.getRunDiagnostics(sessionId, requestId, sessionOwner(sessionId) || undefined))
    } catch (e) {
      setError(String(e))
    }
  }

  /** 恢复只提交来源 Run；具体历史和副作用保护由后端校验。 */
  const act = async (mode: 'continue' | 'retry') => {
    setBusy(true)
    setError('')
    try {
      await recover(sessionId, requestId, mode)
      await load()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="mt-2 text-xs text-content-secondary" onToggle={(event) => {
      if (event.currentTarget.open) void load()
    }}>
      <summary className="cursor-pointer">{t('run_details')}</summary>
      {error && <div className="mt-1 text-danger break-words">{error}</div>}
      {data && <div className="mt-2 space-y-2">
        <div>{t('run_duration')}: {data.duration_ms == null ? '—' : `${(data.duration_ms / 1000).toFixed(2)} s`}
          {' · '}{t('run_known_tokens')}: {data.usage.total_tokens ?? '—'}</div>
        {data.error_code && <div>{t('run_error')}: {data.error_code}</div>}
        {data.steps.map((step) => <div key={step.step_id} className="flex flex-wrap gap-2">
          <span>{step.kind === 'tool' ? step.data.call?.name : `${t('run_model_attempt')} ${step.data.attempt ?? ''}`}</span>
          <span>{t(`run_step_${step.status}`)}</span>
          <span>{step.duration_ms == null ? '—' : `${step.duration_ms} ms`}</span>
          {step.error_code && <span>{step.error_code}</span>}
        </div>)}
        {data.requires_acknowledgement && <div className="text-danger">{t('run_recovery_warning')}</div>}
        {(data.can_continue || data.can_retry) && <div className="flex gap-3">
          {data.can_continue && <button className="cursor-pointer text-accent disabled:opacity-50"
            disabled={busy || isStreaming} onClick={() => void act('continue')}>{t('run_continue')}</button>}
          {data.can_retry && <button className="cursor-pointer text-accent disabled:opacity-50"
            disabled={busy || isStreaming} onClick={() => void act('retry')}>{t('run_retry')}</button>}
        </div>}
      </div>}
    </details>
  )
}
