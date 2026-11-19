import { useEffect, useState } from 'react'
import { api } from './api'

type Snapshot<T> = { path: string; data?: T; error?: string }

export function useApi<T>(path: string | null, pollMs = 0) {
  const [snapshot, setSnapshot] = useState<Snapshot<T>>()
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    let timer: number | undefined

    async function load() {
      try {
        const data = await api<T>(path!, { signal: controller.signal })
        if (!controller.signal.aborted) setSnapshot({ path: path!, data })
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : 'The request failed.'
          setSnapshot((old) => ({ path: path!, data: old?.path === path ? old.data : undefined, error: message }))
        }
      } finally {
        if (pollMs && !controller.signal.aborted) timer = window.setTimeout(load, pollMs)
      }
    }

    void load()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [path, pollMs, revision])

  const current = snapshot?.path === path ? snapshot : undefined
  return { ...current, loading: Boolean(path && !current), refresh: () => setRevision((value) => value + 1) }
}
