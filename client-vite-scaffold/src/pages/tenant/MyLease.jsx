import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { acceptLease, fetchMyLeases } from '../../store/leasesSlice'
import { errorText } from '../../store/helpers'
import { api } from '../../services/api'
import { Empty, ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import { fmtDate, fmtDateTime, money } from '../../utils/format'

const LEASE_LABEL = { pending: 'Waiting for you to accept', active: 'Active', ended: 'Ended' }
const REMINDER_LABELS = { email: 'Email', sms: 'SMS', whatsapp: 'WhatsApp' }

function ReminderPreferences({ lease }) {
  const [preferences, setPreferences] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [verifyKind, setVerifyKind] = useState('')
  const [code, setCode] = useState('')
  const [phone, setPhone] = useState('')

  useEffect(() => {
    let active = true
    api.reminderPreferences(lease.id).then((value) => {
      if (active) setPreferences(value.channels)
    }).catch((err) => {
      if (active) setError(err.message)
    })
    return () => { active = false }
  }, [lease.id])

  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const selected = preferences.filter((item) => item.enabled).map((item) => item.channel)
      setPreferences((await api.saveReminderPreferences(lease.id, selected)).channels)
      setNotice('Reminder preferences saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function verify(kind) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (verifyKind === kind) {
        await api.confirmReminderCode(kind, code)
        const result = await api.reminderPreferences(lease.id)
        setPreferences((current) => current.map((item) => ({
          ...item, verified: result.channels.find((channel) => channel.channel === item.channel)?.verified,
        })))
        setVerifyKind('')
        setCode('')
        setNotice('Contact verified.')
      } else {
        const result = await api.requestReminderCode(kind, kind === 'phone' ? phone || null : null)
        setVerifyKind(kind)
        setCode(result.demo_code || '')
        setNotice('Enter the verification code.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Receive notices and reminders</h2>
      <p>Choose where you want to receive notices and reminders. They are always available in your inbox.
        Rent reminders start 3 days before your due date and stop once your rent is paid.</p>
      <p><Link to="/inbox">Open inbox</Link></p>
      <ErrorNote>{error}</ErrorNote>
      <SuccessNote>{notice}</SuccessNote>
      {preferences ? (
        <form onSubmit={save}>
          <fieldset disabled={busy}>
            <legend>Contact preferences</legend>
            <p>In-app inbox · Always on</p>
            {preferences.map((item) => (
              <label key={item.channel} className="checkbox-row">
                <input type="checkbox" checked={item.enabled} disabled={!item.verified && !item.enabled}
                  onChange={(event) => setPreferences(preferences.map((row) =>
                    row.channel === item.channel ? { ...row, enabled: event.target.checked } : row))} />
                {REMINDER_LABELS[item.channel]}{!item.verified && ' · Verification required'}
              </label>
            ))}
            {['email', 'phone'].filter((kind) => preferences.some((item) =>
              !item.verified && (kind === 'email') === (item.channel === 'email'))).map((kind) => (
              <div key={kind}>
                {kind === 'phone' && verifyKind !== kind && <label className="field">
                  <span>Mobile number</span>
                  <input type="tel" value={phone} placeholder="Use your saved number or enter a new one"
                    onChange={(event) => setPhone(event.target.value)} />
                </label>}
                {verifyKind === kind && <label className="field">
                  <span>Six-digit code</span>
                  <input inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} />
                </label>}
                <button type="button" className="btn btn-secondary" onClick={() => verify(kind)}>
                  {verifyKind === kind ? 'Confirm code' : `Verify ${kind}`}
                </button>
              </div>
            ))}
          </fieldset>
          <button className="btn btn-primary" disabled={busy || !preferences.some((item) => item.enabled)
            || preferences.some((item) => item.enabled && !item.verified)}>Save preferences</button>
        </form>
      ) : !error && <Loading />}
    </section>
  )
}

function LeaseCard({ lease }) {
  const dispatch = useDispatch()
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function run(kind, task, done) {
    setBusy(kind)
    setError('')
    setNotice('')
    try {
      await task()
      if (done) setNotice(done)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <article className="panel lease">
      <header className="lease-head">
        <div>
          <h2>
            {lease.property}, unit {lease.unit}
          </h2>
          <p className="muted">
            {fmtDate(lease.start_date)} to {fmtDate(lease.end_date)}
          </p>
        </div>
        <span className={`badge badge-${lease.status === 'active' ? 'ok' : 'brand'}`}>
          {LEASE_LABEL[lease.status] || lease.status}
        </span>
      </header>

      <dl className="facts">
        <div>
          <dt>Monthly rent</dt>
          <dd>{money(lease.monthly_rent)}</dd>
        </div>
        <div>
          <dt>Rent is due</dt>
          <dd>By day {lease.due_day} of each month</dd>
        </div>
        <div>
          <dt>Deposit</dt>
          <dd>{money(lease.deposit)}</dd>
        </div>
        {lease.accepted_at && (
          <div>
            <dt>Accepted</dt>
            <dd>{fmtDateTime(lease.accepted_at)}</dd>
          </div>
        )}
      </dl>

      <ErrorNote>{error}</ErrorNote>
      <SuccessNote>{notice}</SuccessNote>

      <div className="actions actions-start">
        <button
          type="button"
          className="btn btn-quiet"
          disabled={busy === 'pdf'}
          onClick={() => run('pdf', () => api.downloadLeasePdf(lease.id))}
        >
          {busy === 'pdf' ? 'Preparing' : 'Download lease (PDF)'}
        </button>
        {lease.status === 'pending' && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy === 'accept'}
            onClick={() =>
              run('accept', () => dispatch(acceptLease(lease.id)).unwrap(), 'Lease accepted. You are now an active tenant.')
            }
          >
            {busy === 'accept' ? 'Accepting' : 'Accept lease'}
          </button>
        )}
      </div>
      {lease.status === 'pending' && (
        <p className="muted small">
          Accepting records the date and time against your login. Read the PDF first.
        </p>
      )}
    </article>
  )
}

export default function MyLease() {
  const dispatch = useDispatch()
  const { items, status, error } = useSelector((s) => s.leases)

  useEffect(() => {
    dispatch(fetchMyLeases())
  }, [dispatch])

  return (
    <>
      <header className="page-head">
        <h1>My lease</h1>
        <p>Your lease agreement and the terms you agreed to.</p>
      </header>

      {status === 'loading' && items.length === 0 && <Loading />}
      <ErrorNote>{status === 'failed' ? error : ''}</ErrorNote>
      {status === 'ready' && items.length === 0 && (
        <Empty title="No lease yet">
          Once a landlord approves your application and issues a lease, it appears here. Check{' '}
          <Link to="/applications">My applications</Link> for progress.
        </Empty>
      )}

      {items.map((lease) => (
        <div key={lease.id}>
          <LeaseCard lease={lease} />
          {['active', 'pending'].includes(lease.status) && <ReminderPreferences lease={lease} />}
        </div>
      ))}
    </>
  )
}
