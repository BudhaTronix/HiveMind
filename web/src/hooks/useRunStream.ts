import { useEffect, useRef } from 'react'
import { api, streamUrl } from '../api'
import type { DashboardAction } from '../state/reducer'
import type { StreamEnvelope } from '../types'

export function useRunStream(runId: string | null, dispatch: React.Dispatch<DashboardAction>) {
  const attempts = useRef(0)

  useEffect(() => {
    if (!runId) return
    let stopped = false
    let socket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let flushTimer: number | null = null
    let pending: StreamEnvelope[] = []

    const flush = () => {
      flushTimer = null
      if (!pending.length || stopped) return
      const envelopes = pending
      pending = []
      dispatch({ type: 'envelopes', envelopes })
    }

    const enqueue = (envelope: StreamEnvelope) => {
      pending.push(envelope)
      if (flushTimer === null) flushTimer = window.setTimeout(flush, 32)
    }

    const connect = () => {
      if (stopped) return
      dispatch({ type: 'set_connection', connection: attempts.current ? 'reconnecting' : 'connecting' })
      socket = new WebSocket(streamUrl(runId))
      socket.onopen = () => {
        attempts.current = 0
        dispatch({ type: 'set_connection', connection: 'live' })
      }
      socket.onmessage = (message) => {
        const envelope = JSON.parse(String(message.data)) as StreamEnvelope
        if (envelope.type === 'run_state') {
          flush()
          void api.snapshot(runId).then((snapshot) => {
            if (!stopped) dispatch({ type: 'snapshot', snapshot, reconnect: true })
          })
        } else if (envelope.type === 'error' && envelope.data.code === 'resync_required') {
          socket?.close()
        } else {
          enqueue(envelope)
        }
      }
      socket.onerror = () => socket?.close()
      socket.onclose = () => {
        if (stopped) return
        attempts.current += 1
        dispatch({ type: 'set_connection', connection: 'reconnecting' })
        const delay = Math.min(750 * 2 ** Math.min(attempts.current, 4), 8_000)
        reconnectTimer = window.setTimeout(connect, delay)
      }
    }

    connect()
    return () => {
      stopped = true
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      if (flushTimer !== null) window.clearTimeout(flushTimer)
      pending = []
      socket?.close()
      dispatch({ type: 'set_connection', connection: 'offline' })
    }
  }, [dispatch, runId])
}
