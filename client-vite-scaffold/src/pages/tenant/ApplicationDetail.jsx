import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { fetchApplication } from '../../store/applicationsSlice'
import { ErrorNote, Loading } from '../../components/Feedback'
import StatusBadge from '../../components/StatusBadge'
import Tracker from '../../components/Tracker'
import { fmtDate, money, percent } from '../../utils/format'

export default function ApplicationDetail() {
  const { id } = useParams()
  const dispatch = useDispatch()
  const application = useSelector((s) => s.applications.items.find((a) => a.id === Number(id)))
  const loadError = useSelector((s) => s.applications.error)

  useEffect(() => {
    dispatch(fetchApplication(Number(id)))
  }, [dispatch, id])

  if (!application?.timeline) {
    return loadError ? <ErrorNote>{loadError}</ErrorNote> : <Loading />
  }

  const a = application
  return (
    <>
      <p className="crumb">
        <Link to="/applications">My applications</Link>
      </p>

      <section className="ticket" aria-label="Application reference">
        <div>
          <div className="ticket-label">Reference</div>
          <div className="ticket-ref">{a.reference_no}</div>
        </div>
        <div className="ticket-unit">
          <div>
            {a.unit.property}, unit {a.unit.unit_number}
          </div>
          <div className="muted">Sent {fmtDate(a.created_at)}</div>
        </div>
        <StatusBadge status={a.status} role="tenant" />
      </section>

      <div className="two-col">
        <section className="panel">
          <h2>Progress</h2>
          <Tracker application={a} audience="tenant" />
        </section>

        <section className="panel">
          <h2>Your application</h2>
          <dl className="facts">
            <div>
              <dt>Monthly rent</dt>
              <dd>{money(a.unit.monthly_rent)}</dd>
            </div>
            <div>
              <dt>Your income</dt>
              <dd>{money(a.monthly_income)}</dd>
            </div>
            <div>
              <dt>Rent as share of income</dt>
              <dd>{percent(a.rent_to_income)}</dd>
            </div>
            <div>
              <dt>Credit score</dt>
              <dd>{a.credit_score ?? 'Not checked yet'}</dd>
            </div>
            <div>
              <dt>Credit check consent</dt>
              <dd>{fmtDate(a.consent_at)}</dd>
            </div>
          </dl>

          {a.status === 'lease_issued' && (
            <div className="callout">
              <strong>Your lease is ready.</strong>
              <p>Read it and accept to finish moving in.</p>
              <Link to="/lease" className="btn btn-primary">
                Open my lease
              </Link>
            </div>
          )}
          {a.status === 'active_tenant' && (
            <div className="callout callout-ok">
              <strong>You are an active tenant.</strong>
              <p>
                Your lease is in <Link to="/lease">My lease</Link>.
              </p>
            </div>
          )}
          {a.status === 'rejected' && (
            <div className="callout callout-bad">
              <strong>The landlord chose not to go ahead with this application.</strong>
              <p>
                You can look at other <Link to="/units">vacant units</Link>.
              </p>
            </div>
          )}
        </section>
      </div>
    </>
  )
}
