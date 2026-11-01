import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

type User = {
  email: string
  full_name: string
  role: string
}

type Alert = {
  id: number
  channel: string
  message: string
  created_at: string
}

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const CURRENT_YEAR = new Date().getFullYear()

function App() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [accessToken, setAccessToken] = useState('')
  const [user, setUser] = useState<User | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [isSigningIn, setIsSigningIn] = useState(false)
  const [isLoadingAlerts, setIsLoadingAlerts] = useState(false)
  const [error, setError] = useState('')
  const [refreshCount, setRefreshCount] = useState(0)

  useEffect(() => {
    if (!accessToken) return

    const controller = new AbortController()

    async function loadAlerts() {
      setIsLoadingAlerts(true)
      setError('')

      try {
        const response = await fetch(`${API_URL}/notifications/me`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: controller.signal,
        })

        if (response.status === 401) {
          setAccessToken('')
          setUser(null)
          setAlerts([])
          setError('Your session expired. Please sign in again.')
          return
        }
        if (!response.ok) {
          throw new Error('Could not load your alerts. Please try again.')
        }

        const result = (await response.json()) as Alert[]
        setAlerts(result)
      } catch (requestError) {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError(requestError instanceof Error ? requestError.message : 'Something went wrong.')
      } finally {
        if (!controller.signal.aborted) setIsLoadingAlerts(false)
      }
    }

    void loadAlerts()
    return () => controller.abort()
  }, [accessToken, refreshCount])

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSigningIn(true)
    setError('')

    try {
      const response = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      if (response.status === 401) {
        throw new Error('That email and password do not match.')
      }
      if (!response.ok) {
        throw new Error('Could not sign in. Check that the Land-Keep API is running.')
      }

      const result = (await response.json()) as { access_token: string }
      const profileResponse = await fetch(`${API_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${result.access_token}` },
      })
      if (!profileResponse.ok) {
        throw new Error('Signed in, but could not load your profile.')
      }

      setUser((await profileResponse.json()) as User)
      setAccessToken(result.access_token)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Something went wrong.')
    } finally {
      setIsSigningIn(false)
    }
  }

  function signOut() {
    setAccessToken('')
    setUser(null)
    setAlerts([])
    setPassword('')
    setError('')
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Land-Keep home">
          <span className="brand-mark" aria-hidden="true">L</span>
          <span>land<span className="brand-accent">keep</span></span>
        </a>
        <div className="topbar-right">
          <span className="system-status"><span /> Alert center</span>
          {user && (
            <button className="signout-button" type="button" onClick={signOut}>
              Sign out
            </button>
          )}
        </div>
      </header>

      <main>
        <section className="hero-section">
          <div className="hero-copy">
            <p className="eyebrow">A clearer way to rent</p>
            <h1>The right update,<br />right on time.</h1>
            <p className="hero-description">
              Rent, repairs, and property notices — all your important updates in one place.
            </p>
          </div>
          <div className="hero-art" aria-hidden="true">
            <span className="hero-orbit orbit-one" />
            <span className="hero-orbit orbit-two" />
            <span className="hero-bell">✳</span>
            <span className="hero-spark spark-one">✦</span>
            <span className="hero-spark spark-two">✦</span>
          </div>
        </section>

        {!user ? (
          <section className="signin-card" aria-labelledby="signin-heading">
            <div className="card-heading">
              <div>
                <p className="eyebrow">Your personal space</p>
                <h2 id="signin-heading">Sign in to your alerts</h2>
              </div>
              <span className="lock-mark" aria-hidden="true">↗</span>
            </div>
            <p className="card-description">
              Use your Land-Keep account to see updates about your applications and lease.
            </p>
            <form className="signin-form" onSubmit={signIn}>
              <label htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              {error && <p className="error-message" role="alert">{error}</p>}
              <button className="primary-button" type="submit" disabled={isSigningIn}>
                {isSigningIn ? 'Signing in…' : 'Continue to alerts'}
                {!isSigningIn && <span aria-hidden="true">→</span>}
              </button>
            </form>
            <p className="privacy-note">
              <span aria-hidden="true">◈</span> Your account details stay private and secure.
            </p>
          </section>
        ) : (
          <section className="inbox-section" aria-labelledby="inbox-heading">
            <div className="inbox-heading">
              <div>
                <p className="eyebrow">{user.role} account · {user.full_name}</p>
                <h2 id="inbox-heading">Your alert inbox</h2>
                <p className="card-description">
                  Updates from your Land-Keep activity, gathered in one place.
                </p>
              </div>
              <button
                className="refresh-button"
                type="button"
                onClick={() => setRefreshCount((count) => count + 1)}
                disabled={isLoadingAlerts}
              >
                <span aria-hidden="true">↻</span> Refresh
              </button>
            </div>
            {error && <p className="error-message inbox-error" role="alert">{error}</p>}
            <div className="inbox-meta">
              <span>RECENT UPDATES</span>
              <span>
                {isLoadingAlerts
                  ? 'Checking for updates…'
                  : `${alerts.length} ${alerts.length === 1 ? 'alert' : 'alerts'}`}
              </span>
            </div>
            {alerts.length > 0 ? (
              <ul className="alert-list">
                {alerts.map((alert) => (
                  <li className="alert-card" key={alert.id}>
                    <span className="alert-icon" aria-hidden="true">✳</span>
                    <div className="alert-content">
                      <div className="alert-card-top">
                        <span className="alert-channel">{alert.channel.replace('_', ' ')}</span>
                        <time dateTime={alert.created_at}>
                          {new Intl.DateTimeFormat(undefined, {
                            dateStyle: 'medium',
                            timeStyle: 'short',
                          }).format(new Date(alert.created_at))}
                        </time>
                      </div>
                      <p>{alert.message}</p>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              !isLoadingAlerts && (
                <div className="empty-state">
                  <span className="empty-icon" aria-hidden="true">✳</span>
                  <h3>You’re all caught up</h3>
                  <p>When there’s an update about your application or lease, it’ll show up here.</p>
                </div>
              )
            )}
          </section>
        )}

        <section className="feature-row" aria-label="Alert categories">
          <article className="feature-item">
            <span className="feature-icon rent-icon" aria-hidden="true">⌂</span>
            <div><h3>Rent reminders</h3><p>Know what’s due, before it’s due.</p></div>
          </article>
          <article className="feature-item">
            <span className="feature-icon repair-icon" aria-hidden="true">✳</span>
            <div><h3>Repair updates</h3><p>Keep track as a request moves along.</p></div>
          </article>
          <article className="feature-item">
            <span className="feature-icon notice-icon" aria-hidden="true">⌑</span>
            <div><h3>Property notices</h3><p>Stay in the loop on what matters.</p></div>
          </article>
        </section>
      </main>

      <footer className="footer">
        <span>© {CURRENT_YEAR} Land-Keep</span>
        <span>Thoughtful updates for better renting.</span>
      </footer>
    </div>
  )
}

export default App
