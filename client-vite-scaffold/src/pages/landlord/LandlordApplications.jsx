import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  convertApplication,
  decideApplication,
  fetchApplication,
  fetchApplications,
  runCreditCheck,
} from '../../store/applicationsSlice'
import { errorText } from '../../store/helpers'
import { Empty, ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import StatusBadge from '../../components/StatusBadge'
import Tracker from '../../components/Tracker'
import { fmtDate, money, percent } from '../../utils/format'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'submitted', label: 'Needs credit check' },
  { key: 'under_review', label: 'Needs decision' },
  { key: 'approved', label: 'Approved' },
  { key: 'lease_issued', label: 'Lease issued' },
  { key: 'active_tenant', label: 'Active' },
  { key: 'rejected', label: 'Rejected' },
]

// These mirror the thresholds in backend/app/services/credit.py.
const SCORE_MIN = 300
const SCORE_MAX = 850
const ZONES = [
  { key: 'decline', label: 'Decline', from: 300, to: 550 },
  { key: 'review', label: 'Review', from: 550, to: 650 },
  { key: 'approve', label: 'Approve', from: 650, to: 850 },
]

const RECOMMENDATION = {
  approve: {
    title: 'The system suggests approving',
    text: 'The score is 650 or higher and the rent is no more than 35% of income.',
  },
  review: {
    title: 'The system suggests a closer look',
    text: 'The score or the rent-to-income ratio is borderline. Check the details before you decide.',
  },
  decline: {
    title: 'The system suggests declining',
    text: 'The score is below 550, or the rent is more than 50% of income.',
  },
}

function ScoreGauge({ score }) {
  const pct = ((score - SCORE_MIN) / (SCORE_MAX - SCORE_MIN)) * 100
  return (
    <div className="gauge" role="img" aria-label={`Credit score ${score} on a scale of ${SCORE_MIN} to ${SCORE_MAX}`}>
      <div className="gauge-bar">
        {ZONES.map((z) => (
          <span
            key={z.key}
            className={`gauge-zone zone-${z.key}`}
            style={{ width: `${((z.to - z.from) / (SCORE_MAX - SCORE_MIN)) * 100}%` }}
          />
        ))}
        <span className="gauge-marker" style={{ left: `${pct}%` }} />
      </div>
      <div className="gauge-labels">
        {ZONES.map((z) => (
          <span key={z.key} style={{ width: `${((z.to - z.from) / (SCORE_MAX - SCORE_MIN)) * 100}%` }}>
            {z.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function nextMonthStart() {
  const d = new Date()
  const next = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  const p = (n) => String(n).padStart(2, '0')
  return `${next.getFullYear()}-${p(next.getMonth() + 1)}-01`
}

function ConvertForm({ application, busy, onConvert }) {
  const rent = application.unit.monthly_rent
  const [form, setForm] = useState({ start_date: nextMonthStart(), term_months: '12', due_day: '1', deposit: String(rent) })
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  function submit(e) {
    e.preventDefault()
    onConvert({
      start_date: form.start_date,
      term_months: Number(form.term_months),
      due_day: Number(form.due_day),
      deposit: Number(form.deposit),
    })
  }

  return (
    <form onSubmit={submit} className="inline-form">
      <label className="field">
        <span>Lease starts</span>
        <input type="date" value={form.start_date} onChange={set('start_date')} required />
      </label>
      <label className="field">
        <span>Length</span>
        <select value={form.term_months} onChange={set('term_months')}>
          <option value="6">6 months</option>
          <option value="12">12 months</option>
          <option value="24">24 months</option>
        </select>
      </label>
      <label className="field">
        <span>Rent due on day</span>
        <input type="number" min="1" max="28" value={form.due_day} onChange={set('due_day')} required />
      </label>
      <label className="field">
        <span>Deposit (R)</span>
        <input type="number" min="0" step="any" value={form.deposit} onChange={set('deposit')} required />
      </label>
      <button type="submit" className="btn btn-primary" disabled={busy}>
        {busy ? 'Creating lease' : 'Convert to tenant and issue lease'}
      </button>
    </form>
  )
}

function Review({ id }) {
  const dispatch = useDispatch()
  const application = useSelector((s) => s.applications.items.find((a) => a.id === id))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    setError('')
    setNotice('')
    setNote('')
    dispatch(fetchApplication(id))
  }, [dispatch, id])

  async function act(kind, action, message) {
    setBusy(kind)
    setError('')
    setNotice('')
    try {
      await dispatch(action).unwrap()
      setNotice(message)
      setNote('')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  if (!application?.timeline) return <Loading />
  const a = application
  const ratioTone = a.rent_to_income <= 0.35 ? 'ok' : a.rent_to_income <= 0.5 ? 'warn' : 'bad'
  const rec = RECOMMENDATION[a.recommendation]

  return (
    <article className="review" aria-label={`Application ${a.reference_no}`}>
      <header className="review-head">
        <div>
          <h2>{a.applicant.full_name}</h2>
          <p className="muted">
            {a.unit.property}, unit {a.unit.unit_number}. Reference {a.reference_no}.
          </p>
        </div>
        <StatusBadge status={a.status} role="landlord" />
      </header>

      <SuccessNote>{notice}</SuccessNote>
      <ErrorNote>{error}</ErrorNote>

      <section className="block">
        <h3>Applicant</h3>
        <dl className="facts facts-wide">
          <div>
            <dt>Monthly income</dt>
            <dd>{money(a.monthly_income)}</dd>
          </div>
          <div>
            <dt>Rent</dt>
            <dd>{money(a.unit.monthly_rent)}</dd>
          </div>
          <div>
            <dt>Rent as share of income</dt>
            <dd className={`tone-${ratioTone}`}>{percent(a.rent_to_income)}</dd>
          </div>
          <div>
            <dt>Employer</dt>
            <dd>{a.employer || 'Not given'}</dd>
          </div>
          <div>
            <dt>ID number</dt>
            <dd>{a.id_number}</dd>
          </div>
          <div>
            <dt>Consent given</dt>
            <dd>{a.consent_given ? fmtDate(a.consent_at) : 'Not given'}</dd>
          </div>
          <div>
            <dt>Contact</dt>
            <dd>
              {a.applicant.email}
              <br />
              {a.applicant.phone || 'No phone'}
            </dd>
          </div>
        </dl>
      </section>

      <section className="block">
        <h3>Credit check</h3>
        {a.credit_score == null ? (
          <div className="block-action">
            <p className="muted">Not run yet. The applicant gave consent, so you can verify them now.</p>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy === 'check' || a.status !== 'submitted'}
              onClick={() => act('check', runCreditCheck(id), 'Credit check done. Review the result and decide.')}
            >
              {busy === 'check' ? 'Checking' : 'Run credit check'}
            </button>
          </div>
        ) : (
          <>
            <div className="score">
              <span className="score-number">{a.credit_score}</span>
              <span className="muted">out of {SCORE_MAX}</span>
            </div>
            <ScoreGauge score={a.credit_score} />
            {rec && (
              <div className={`recommend recommend-${a.recommendation}`}>
                <strong>{rec.title}</strong>
                <p>{rec.text}</p>
              </div>
            )}
          </>
        )}
      </section>

      {a.status === 'under_review' && (
        <section className="block">
          <h3>Your decision</h3>
          <p className="muted">The score is a recommendation. The decision is yours.</p>
          <label className="field">
            <span>Note for the record (optional)</span>
            <textarea rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="actions actions-start">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!!busy}
              onClick={() =>
                act(
                  'approve',
                  decideApplication({ id, decision: 'approved', note }),
                  'Approved. The applicant was told by email and SMS.',
                )
              }
            >
              {busy === 'approve' ? 'Approving' : 'Approve'}
            </button>
            <button
              type="button"
              className="btn btn-danger"
              disabled={!!busy}
              onClick={() =>
                act(
                  'reject',
                  decideApplication({ id, decision: 'rejected', note }),
                  'Rejected. The applicant was told by email and SMS.',
                )
              }
            >
              {busy === 'reject' ? 'Rejecting' : 'Reject'}
            </button>
          </div>
        </section>
      )}

      {a.status === 'approved' && (
        <section className="block">
          <h3>Make them a tenant</h3>
          <p className="muted">
            Their details carry over. LandKeep writes the lease and sends it to {a.applicant.full_name.split(' ')[0]} to
            accept.
          </p>
          <ConvertForm
            application={a}
            busy={busy === 'convert'}
            onConvert={(body) =>
              act(
                'convert',
                convertApplication({ id, ...body }),
                'Lease issued. The applicant was told by email and SMS and can accept it in LandKeep.',
              )
            }
          />
        </section>
      )}

      {a.status === 'lease_issued' && (
        <section className="block">
          <h3>Lease</h3>
          <p className="muted">The lease has been sent. Waiting for the tenant to accept it.</p>
        </section>
      )}

      {a.status === 'active_tenant' && (
        <section className="block">
          <h3>Tenancy</h3>
          <p className="muted">The lease was accepted and the unit is now occupied.</p>
        </section>
      )}

      <section className="block">
        <h3>Progress</h3>
        <Tracker application={a} audience="landlord" />
      </section>
    </article>
  )
}

export default function LandlordApplications() {
  const { id } = useParams()
  const dispatch = useDispatch()
  const { items, status, error } = useSelector((s) => s.applications)
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    dispatch(fetchApplications('landlord'))
  }, [dispatch])

  const counts = useMemo(() => {
    const c = { all: items.length }
    for (const a of items) c[a.status] = (c[a.status] || 0) + 1
    return c
  }, [items])

  const visible = filter === 'all' ? items : items.filter((a) => a.status === filter)
  const selectedId = id ? Number(id) : null

  // On a phone the details sit below the list, so bring them into view when one is picked.
  useEffect(() => {
    if (selectedId && window.matchMedia('(max-width: 880px)').matches) {
      document.querySelector('.split-detail')?.scrollIntoView({ block: 'start' })
    }
  }, [selectedId])

  return (
    <>
      <header className="page-head">
        <h1>Applications</h1>
        <p>Verify applicants, make the decision and turn approved applicants into tenants.</p>
      </header>

      <div className="chips" role="group" aria-label="Filter applications">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={filter === f.key ? 'chip active' : 'chip'}
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
          >
            {f.label} <span className="chip-count">{counts[f.key] || 0}</span>
          </button>
        ))}
      </div>

      {status === 'loading' && items.length === 0 && <Loading />}
      <ErrorNote>{status === 'failed' ? error : ''}</ErrorNote>

      <div className="split">
        <div className="split-list">
          {status === 'ready' && visible.length === 0 && (
            <Empty title="Nothing here">No applications match this filter.</Empty>
          )}
          <ul className="row-list">
            {visible.map((a) => (
              <li key={a.id}>
                <Link
                  to={`/landlord/applications/${a.id}`}
                  className={a.id === selectedId ? 'row-link selected' : 'row-link'}
                  aria-current={a.id === selectedId ? 'true' : undefined}
                >
                  <div className="row-main">
                    <h3>{a.applicant.full_name}</h3>
                    <p className="muted">
                      {a.unit.property}, unit {a.unit.unit_number}
                    </p>
                    <p className="muted small">
                      {a.reference_no}. {fmtDate(a.created_at)}
                    </p>
                  </div>
                  <StatusBadge status={a.status} role="landlord" />
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className="split-detail">
          {selectedId ? (
            <Review key={selectedId} id={selectedId} />
          ) : (
            <Empty title="Pick an application">
              Choose one from the list to see the applicant, run the credit check and decide.
            </Empty>
          )}
        </div>
      </div>
    </>
  )
}
