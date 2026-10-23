import { useEffect, useState } from 'react'

export function useSse(taskId: number | null) {
  const [events, setEvents] = useState<any[]>([])
  const [progress, setProgress] = useState({ reviewed: 0, total: 0 })
  const [status, setStatus] = useState<string>('')

  useEffect(() => {
    if (!taskId) return

    const token = localStorage.getItem('accessToken')
    const url = `/api/v1/reviews/${taskId}/stream`
    const controller = new AbortController()

    fetch(url, {
      signal: controller.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then(async (response) => {
      if (!response.ok) throw new Error(`SSE request failed: ${response.status}`)
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (reader) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const data = JSON.parse(line.substring(5).trim())
              setEvents((prev) => [...prev, data])
              if (data.eventType === 'PROGRESS_UPDATE') {
                setProgress({ reviewed: data.reviewedClauses, total: data.totalClauses })
              }
              if (data.eventType === 'REVIEW_COMPLETE') {
                setStatus('COMPLETED')
              }
            } catch {}
          }
        }
      }
    }).catch(() => {})

    return () => controller.abort()
  }, [taskId])

  return { events, progress, status }
}
