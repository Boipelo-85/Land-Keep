import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { clearAuthError, login, register } from '../store/authSlice'
import { ErrorNote } from '../components/Feedback'

const DEMOS = [
  { label: 'Landlord demo', email: 'landlord@landkeep.test' },
  { label: 'Applicant demo', email: 'applicant@landkeep.test' },
]

export default function Login() {
  const dispatch = useDispatch()
  const { user, status, error } = useSelector((s) => s.auth)
  const [mode, setMode] = useState('signin')
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', password: '' })

  if (user) return <Navigate to="/" replace />

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  const creating = mode === 'register'

  function switchMode(next) {
    setMode(next)
    dispatch(clearAuthError())
  }

  function submit(e) {
    e.preventDefault()
    if (creating) {
      dispatch(register({ ...form, phone: form.phone || null }))
    } else {
      dispatch(login({ email: form.email, password: form.password }))
    }
  }

  return (
    <div className="auth">
      <section className="auth-intro">
        <div className="brand">LandKeep</div>
        <h1>Everything between applying for a unit and living in it, in one place.</h1>
        <p>
          Apply, get verified, sign your lease and report problems without chasing anyone on WhatsApp. Landlords
          review, decide and manage the whole tenancy from the same screen.
        </p>
      </section>

      <section className="auth-form" aria-labelledby="auth-title">
        <h2 id="auth-title">{creating ? 'Create an applicant account' : 'Sign in'}</h2>

        <form onSubmit={submit} noValidate={false}>
          {creating && (
            <>
              <label className="field">
                <span>Full name</span>
                <input value={form.full_name} onChange={set('full_name')} required minLength={2} autoComplete="name" />
              </label>
              <label className="field">
                <span>Mobile number</span>
                <input value={form.phone} onChange={set('phone')} placeholder="+27 82 555 0123" autoComplete="tel" />
                <small>We send approval updates here by SMS.</small>
              </label>
            </>
          )}
          <label className="field">
            <span>Email</span>
            <input type="email" value={form.email} onChange={set('email')} required autoComplete="email" />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={form.password}
              onChange={set('password')}
              required
              minLength={creating ? 8 : 1}
              autoComplete={creating ? 'new-password' : 'current-password'}
            />
            {creating && <small>At least 8 characters.</small>}
          </label>

          <ErrorNote>{error}</ErrorNote>

          <button type="submit" className="btn btn-primary btn-block" disabled={status === 'loading'}>
            {status === 'loading' ? 'Please wait' : creating ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <p className="auth-switch">
          {creating ? 'Already have an account?' : 'Applying for a unit?'}{' '}
          <button type="button" className="link-btn" onClick={() => switchMode(creating ? 'signin' : 'register')}>
            {creating ? 'Sign in' : 'Create an account'}
          </button>
        </p>

        {!creating && (
          <div className="demo">
            <p>Demo accounts use the password <strong>password123</strong>.</p>
            <div className="demo-buttons">
              {DEMOS.map((d) => (
                <button
                  key={d.email}
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => setForm((f) => ({ ...f, email: d.email, password: 'password123' }))}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
