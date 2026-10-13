import { useMemo, useState } from 'react'

type Level = 'A1' | 'A2' | 'B1'
type Topic = 'ordering coffee' | 'shopping' | 'introducing yourself'

const levels: Level[] = ['A1', 'A2', 'B1']
const topics: Topic[] = ['ordering coffee', 'shopping', 'introducing yourself']

type SessionCreateResponse = {
  session_id: string
  conversation_url: string
  max_duration_seconds: number
  mock_mode: boolean
}

async function requestMediaPermissions(): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Your browser does not support microphone/camera access.')
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true })
  stream.getTracks().forEach((track) => track.stop())
}

export default function App() {
  const [level, setLevel] = useState<Level>('A1')
  const [topic, setTopic] = useState<Topic>('introducing yourself')
  const [loading, setLoading] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [conversationUrl, setConversationUrl] = useState('')
  const [maxDurationSeconds, setMaxDurationSeconds] = useState<number | null>(null)
  const [mockMode, setMockMode] = useState<boolean | null>(null)

  const inConversation = Boolean(sessionId && conversationUrl)

  const statusText = useMemo(() => {
    if (loading) return 'Starting conversation…'
    if (ending) return 'Ending conversation…'
    if (!inConversation) return 'Ready to start.'
    const suffix = maxDurationSeconds ? ` Max duration: ${Math.floor(maxDurationSeconds / 60)} min.` : ''
    return `Conversation started.${suffix}`
  }, [loading, ending, inConversation, maxDurationSeconds])

  const startConversation = async () => {
    setLoading(true)
    setError('')

    try {
      await requestMediaPermissions()
      const response = await fetch('/api/session/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level, topic })
      })

      const body = (await response.json()) as SessionCreateResponse | { detail?: string }
      if (!response.ok) {
        const detail = typeof body === 'object' && body && 'detail' in body ? body.detail : undefined
        throw new Error(detail ?? 'Failed to start conversation.')
      }

      const success = body as SessionCreateResponse
      setSessionId(success.session_id)
      setConversationUrl(success.conversation_url)
      setMaxDurationSeconds(success.max_duration_seconds)
      setMockMode(success.mock_mode)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start conversation.')
    } finally {
      setLoading(false)
    }
  }

  const endConversation = async () => {
    if (!sessionId) return

    setEnding(true)
    setError('')

    try {
      const response = await fetch('/api/session/end', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      })

      if (!response.ok) {
        const body = (await response.json()) as { detail?: string }
        throw new Error(body.detail ?? 'Failed to end conversation.')
      }

      setSessionId('')
      setConversationUrl('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to end conversation.')
    } finally {
      setEnding(false)
    }
  }

  return (
    <main className="page">
      <section className="card">
        <h1>My German Tutor</h1>

        <div className="controls">
          <label>
            Level
            <select value={level} onChange={(event) => setLevel(event.target.value as Level)} disabled={inConversation || loading}>
              {levels.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>

          <label>
            Topic
            <select value={topic} onChange={(event) => setTopic(event.target.value as Topic)} disabled={inConversation || loading}>
              {topics.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="buttons">
          <button onClick={startConversation} disabled={loading || ending || inConversation}>
            Start conversation
          </button>
          <button className="secondary" onClick={endConversation} disabled={!inConversation || ending}>
            End conversation
          </button>
        </div>

        <p className="status">{statusText}</p>
        {mockMode && <p className="status warning">Mock mode enabled: this is a local placeholder session.</p>}
        {error && <p className="status error">{error}</p>}

        <div className="video-shell">
          {conversationUrl ? (
            <iframe
              title="Tavus Conversation"
              src={conversationUrl}
              allow="camera; microphone; autoplay; fullscreen"
              referrerPolicy="strict-origin-when-cross-origin"
            />
          ) : (
            <div className="video-placeholder">Your Tavus conversation will appear here after you start.</div>
          )}
        </div>
      </section>
    </main>
  )
}
