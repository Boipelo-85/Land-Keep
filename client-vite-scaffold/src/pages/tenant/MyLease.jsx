import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { acceptLease, fetchMyLeases } from '../../store/leasesSlice'
import { errorText } from '../../store/helpers'
import { api } from '../../services/api'
import { Empty, ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import { fmtDate, fmtDateTime, money } from '../../utils/format'

const LEASE_LABEL = { pending: 'Waiting for you to accept', active: 'Active', ended: 'Ended' }

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
        <LeaseCard key={lease.id} lease={lease} />
      ))}
    </>
  )
}
