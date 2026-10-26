import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

type SetupStatus = {
  status: 'idle' | 'deploying_model' | 'creating_avatar' | 'ready' | 'error'
  step: string
  logs: string[]
  error: string
  ready: boolean
}

type SessionCreateResponse = {
  session_id: string
  conversation_url: string
  max_duration_seconds: number
  mock_mode: boolean
}

type FeedbackItem = {
  error: string
  correction: string
  rule: string
  explanation: string
  reference: string
  utterance: string
}

const SCENARIOS = [
  { id: 'free', label: 'Free talk' },
  { id: 'interview', label: 'Job interview' },
  { id: 'shopping', label: 'Shopping' },
  { id: 'doctor', label: 'Doctor visit' }
] as const

const LEVELS = ['A1', 'A2', 'B1'] as const

async function requestMediaPermissions(): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Your browser does not support microphone/camera access.')
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true })
  stream.getTracks().forEach((track) => track.stop())
}

export default function App() {
  // Setup wizard state
  const [modalTokenId, setModalTokenId] = useState('')
  const [modalTokenSecret, setModalTokenSecret] = useState('')
  const [tavusApiKey, setTavusApiKey] = useState('')
  const [replicaId, setReplicaId] = useState('')
  const [setup, setSetup] = useState<SetupStatus | null>(null)
  const [setupSubmitting, setSetupSubmitting] = useState(false)

  // Conversation state
  const [scenario, setScenario] = useState<(typeof SCENARIOS)[number]['id']>('free')
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('A2')
  const [loading, setLoading] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [conversationUrl, setConversationUrl] = useState('')
  const [maxDurationSeconds, setMaxDurationSeconds] = useState<number | null>(null)
  const [mockMode, setMockMode] = useState<boolean | null>(null)

  // Feedback
  const [feedback, setFeedback] = useState<FeedbackItem[]>([])
  const feedbackTimer = useRef<number | null>(null)

  const isReady = Boolean(setup?.ready)
  const inConversation = Boolean(sessionId && conversationUrl)

  // Poll setup status while provisioning.
  useEffect(() => {
    if (!setup || setup.ready || setup.status === 'idle' || setup.status === 'error') return
    const timer = window.setInterval(async () => {
      try {
        const resp = await fetch('/api/setup/status')
        const body = (await resp.json()) as SetupStatus
        setSetup(body)
      } catch {
        /* keep last state */
      }
    }, 3000)
    return () => window.clearInterval(timer)
  }, [setup])

  // On first load, check whether setup is already done (e.g. mock mode or restart).
  useEffect(() => {
    fetch('/api/setup/status')
      .then((r) => r.json())
      .then((body: SetupStatus) => {
        if (body.status !== 'idle') setSetup(body)
      })
      .catch(() => undefined)
  }, [])

  // Poll feedback while in a conversation.
  const pollFeedback = useCallback(async () => {
    try {
      const resp = await fetch('/api/feedback')
      const body = (await resp.json()) as { items: FeedbackItem[] }
      setFeedback(body.items ?? [])
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    if (inConversation) {
      pollFeedback()
      feedbackTimer.current = window.setInterval(pollFeedback, 5000)
    }
    return () => {
      if (feedbackTimer.current) window.clearInterval(feedbackTimer.current)
    }
  }, [inConversation, pollFeedback])

  const submitSetup = async (event: React.FormEvent) => {
    event.preventDefault()
    setSetupSubmitting(true)
    setError('')
    try {
      const resp = await fetch('/api/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          modal_token_id: modalTokenId,
          modal_token_secret: modalTokenSecret,
          tavus_api_key: tavusApiKey,
          replica_id: replicaId
        })
      })
      const body = (await resp.json()) as SetupStatus | { detail?: string }
      if (!resp.ok) {
        throw new Error(('detail' in body && body.detail) || 'Setup failed.')
      }
      setSetup(body as SetupStatus)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed.')
    } finally {
      setSetupSubmitting(false)
    }
  }

  const statusText = useMemo(() => {
    if (loading) return 'Starting conversation…'
    if (ending) return 'Ending conversation…'
    if (!inConversation) return 'Ready to start.'
    const suffix = maxDurationSeconds ? ` Maximum duration: ${Math.floor(maxDurationSeconds / 60)} min.` : ''
    return `Conversation started.${suffix}`
  }, [loading, ending, inConversation, maxDurationSeconds])

  const startConversation = async () => {
    setLoading(true)
    setError('')
    setFeedback([])
    try {
      await requestMediaPermissions()
      const response = await fetch('/api/session/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario, level })
      })
      const body = (await response.json()) as SessionCreateResponse | { detail?: string }
      if (!response.ok) {
        const detail = typeof body === 'object' && body && 'detail' in body ? body.detail : undefined
        throw new Error(detail ?? 'Failed to start the conversation.')
      }
      const success = body as SessionCreateResponse
      setSessionId(success.session_id)
      setConversationUrl(success.conversation_url)
      setMaxDurationSeconds(success.max_duration_seconds)
      setMockMode(success.mock_mode)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the conversation.')
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
      setMaxDurationSeconds(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to end conversation.')
    } finally {
      setEnding(false)
    }
  }

  const downloadSummary = () => {
    window.open('/api/feedback/summary', '_blank')
  }

  // --- Setup wizard screen ---------------------------------------------------
  if (!isReady) {
    const provisioning = setup?.status === 'deploying_model' || setup?.status === 'creating_avatar'
    return (
      <main className="page">
        <section className="card">
          <p className="eyebrow">Virtual German Tutor</p>
          <h1>Richten Sie Ihren Tutor ein</h1>
          <p className="intro">
            This app runs entirely on <strong>your own</strong> Modal and Tavus accounts. Paste your
            keys below — they stay on your machine and are used only to deploy the GPU model to your
            Modal account and create your Tavus avatar. Setup takes a few minutes.
          </p>

          <form className="setup-form" onSubmit={submitSetup}>
            <label>
              Modal Token ID
              <input value={modalTokenId} onChange={(e) => setModalTokenId(e.target.value)}
                placeholder="ak-..." required />
            </label>
            <label>
              Modal Token Secret
              <input type="password" value={modalTokenSecret}
                onChange={(e) => setModalTokenSecret(e.target.value)} placeholder="as-..." required />
            </label>
            <label>
              Tavus API Key
              <input type="password" value={tavusApiKey}
                onChange={(e) => setTavusApiKey(e.target.value)} placeholder="Your Tavus API key" required />
            </label>
            <label>
              Tavus Replica ID <span className="hint">(the avatar face, from your Tavus dashboard)</span>
              <input value={replicaId} onChange={(e) => setReplicaId(e.target.value)}
                placeholder="r..." />
            </label>
            <button type="submit" disabled={setupSubmitting || provisioning}>
              {provisioning ? 'Setting up…' : 'Set up my tutor'}
            </button>
          </form>

          {setup && setup.status !== 'idle' && (
            <div className="setup-progress">
              <p className="status">{setup.step}</p>
              {setup.logs.length > 0 && (
                <pre className="setup-logs">{setup.logs.slice(-12).join('\n')}</pre>
              )}
            </div>
          )}
          {setup?.status === 'error' && <p className="status error">Setup failed: {setup.error}</p>}
          {error && <p className="status error">{error}</p>}

          <details className="help">
            <summary>Where do I get these keys?</summary>
            <ul>
              <li><strong>Modal:</strong> create a free account at modal.com, run <code>modal token new</code>, or copy the Token ID/Secret from your Modal settings.</li>
              <li><strong>Tavus:</strong> get an API key and a replica (avatar) id from the Tavus dashboard at platform.tavus.io.</li>
            </ul>
          </details>
        </section>
      </main>
    )
  }

  // --- Tutor screen ----------------------------------------------------------
  return (
    <main className="page wide">
      <section className="card tutor">
        <div className="tutor-main">
          <p className="eyebrow">Virtual German Tutor</p>
          <h1>Üben wir Deutsch!</h1>
          <p className="intro">
            Pick a scenario and level, then talk with your avatar in German. This is a
            language-learning aid — have fun and don't worry about mistakes.
          </p>

          <div className="controls">
            <div className="field">
              <span className="field-label">Scenario</span>
              <div className="pills">
                {SCENARIOS.map((s) => (
                  <button key={s.id} type="button"
                    className={`pill ${scenario === s.id ? 'active' : ''}`}
                    disabled={inConversation}
                    onClick={() => setScenario(s.id)}>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="field">
              <span className="field-label">Level</span>
              <div className="pills">
                {LEVELS.map((l) => (
                  <button key={l} type="button"
                    className={`pill ${level === l ? 'active' : ''}`}
                    disabled={inConversation}
                    onClick={() => setLevel(l)}>
                    {l}
                  </button>
                ))}
              </div>
            </div>
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
          {mockMode && <p className="status warning">Mock mode: this is a local placeholder session.</p>}
          {error && <p className="status error">{error}</p>}

          <div className="video-shell">
            {conversationUrl ? (
              <iframe
                title="German tutor avatar"
                src={conversationUrl}
                allow="camera; microphone; autoplay; fullscreen"
                referrerPolicy="strict-origin-when-cross-origin"
              />
            ) : (
              <div className="video-placeholder">Your German tutor avatar will appear here after you start.</div>
            )}
          </div>
        </div>

        <aside className="feedback-panel">
          <div className="feedback-header">
            <h2>Learn from your mistakes</h2>
            <button className="link" onClick={downloadSummary}>Download summary</button>
          </div>
          {feedback.length === 0 ? (
            <p className="feedback-empty">
              Corrections will appear here as you speak. Keine Fehler bisher — weiter so!
            </p>
          ) : (
            <ul className="feedback-list">
              {feedback.map((item, i) => (
                <li key={i} className="feedback-item">
                  <div className="feedback-rule">{item.rule || 'Correction'}</div>
                  {item.utterance && <p className="feedback-said">You said: “{item.utterance}”</p>}
                  {item.correction && <p className="feedback-correct">✅ {item.correction}</p>}
                  {item.explanation && <p className="feedback-why">{item.explanation}</p>}
                  {item.reference && <p className="feedback-ref">{item.reference}</p>}
                </li>
              ))}
            </ul>
          )}
        </aside>
      </section>
    </main>
  )
}
