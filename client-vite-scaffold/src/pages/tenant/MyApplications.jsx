import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { fetchApplications } from '../../store/applicationsSlice'
import { Empty, ErrorNote, Loading } from '../../components/Feedback'
import StatusBadge from '../../components/StatusBadge'
import { fmtDate } from '../../utils/format'

export default function MyApplications() {
  const dispatch = useDispatch()
  const { items, status, error } = useSelector((s) => s.applications)

  useEffect(() => {
    dispatch(fetchApplications('tenant'))
  }, [dispatch])

  return (
    <>
      <header className="page-head">
        <h1>My applications</h1>
        <p>Every application you have sent, and where it stands.</p>
      </header>

      {status === 'loading' && items.length === 0 && <Loading />}
      <ErrorNote>{status === 'failed' ? error : ''}</ErrorNote>
      {status === 'ready' && items.length === 0 && (
        <Empty title="You have not applied yet">
          Browse the <Link to="/units">vacant units</Link> and send your first application.
        </Empty>
      )}

      <ul className="row-list">
        {items.map((a) => (
          <li key={a.id}>
            <Link to={`/applications/${a.id}`} className="row-link">
              <div className="row-main">
                <h3>
                  {a.unit.property}, unit {a.unit.unit_number}
                </h3>
                <p className="muted">
                  Reference {a.reference_no}. Sent {fmtDate(a.created_at)}.
                </p>
              </div>
              <StatusBadge status={a.status} role="tenant" />
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}
