import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { fetchVacantUnits } from '../../store/unitsSlice'
import { submitApplication } from '../../store/applicationsSlice'
import { errorText } from '../../store/helpers'
import { Empty, ErrorNote, Loading } from '../../components/Feedback'
import Modal from '../../components/Modal'
import { money, percent } from '../../utils/format'

function ApplyForm({ unit, onClose }) {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const [form, setForm] = useState({ monthly_income: '', employer: '', id_number: '', consent: false })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const income = Number(form.monthly_income)
  const ratio = income > 0 ? unit.monthly_rent / income : null
  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (!(income > 0)) return setError('Enter your monthly income before deductions.')
    if (!/^\d{13}$/.test(form.id_number)) return setError('Enter your 13-digit South African ID number.')
    setBusy(true)
    try {
      const application = await dispatch(
        submitApplication({
          unit_id: unit.id,
          monthly_income: income,
          employer: form.employer || null,
          id_number: form.id_number,
          consent_given: form.consent,
        }),
      ).unwrap()
      onClose()
      navigate(`/applications/${application.id}`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <p className="muted">
        {unit.property}, unit {unit.unit_number}. {money(unit.monthly_rent)} per month.
      </p>

      <label className="field">
        <span>Monthly income before deductions (R)</span>
        <input type="number" min="1" step="any" value={form.monthly_income} onChange={set('monthly_income')} required />
        {ratio !== null && (
          <small className={ratio <= 0.35 ? 'hint-ok' : 'hint-warn'}>
            {ratio <= 0.35
              ? `Rent is ${percent(ratio)} of your income. Landlords usually look for 35% or less.`
              : `Rent is ${percent(ratio)} of your income, above the 35% landlords usually look for. You can still apply.`}
          </small>
        )}
      </label>

      <label className="field">
        <span>Employer</span>
        <input value={form.employer} onChange={set('employer')} autoComplete="organization" />
      </label>

      <label className="field">
        <span>ID number</span>
        <input
          inputMode="numeric"
          maxLength={13}
          value={form.id_number}
          onChange={set('id_number')}
          required
          autoComplete="off"
        />
        <small>Used for the credit check. Landlords only see the last 4 digits.</small>
      </label>

      <label className="consent">
        <input type="checkbox" checked={form.consent} onChange={set('consent')} />
        <span>
          I agree that LandKeep may run a credit check on me and share the result with the landlord. I can ask for
          my information to be removed at any time.
        </span>
      </label>

      <ErrorNote>{error}</ErrorNote>

      <div className="actions">
        <button type="button" className="btn btn-quiet" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={!form.consent || busy}>
          {busy ? 'Sending' : 'Send application'}
        </button>
      </div>
    </form>
  )
}

export default function Units() {
  const dispatch = useDispatch()
  const { items, status, error } = useSelector((s) => s.units)
  const [applyFor, setApplyFor] = useState(null)

  useEffect(() => {
    dispatch(fetchVacantUnits())
  }, [dispatch])

  return (
    <>
      <header className="page-head">
        <h1>Find a unit</h1>
        <p>Pick a unit and apply. You can follow your application from the moment you send it.</p>
      </header>

      {status === 'loading' && items.length === 0 && <Loading>Loading units</Loading>}
      <ErrorNote>{status === 'failed' ? error : ''}</ErrorNote>
      {status === 'ready' && items.length === 0 && (
        <Empty title="No vacant units right now">New units appear here as soon as a landlord lists them.</Empty>
      )}

      <ul className="unit-list">
        {items.map((u) => (
          <li key={u.id} className="unit-row">
            <div className="unit-main">
              <h3>
                {u.property}, unit {u.unit_number}
              </h3>
              <p className="muted">
                {u.address}, {u.city}
              </p>
            </div>
            <span className="unit-beds">{u.bedrooms} bedroom{u.bedrooms > 1 ? 's' : ''}</span>
            <span className="unit-rent">
              {money(u.monthly_rent)} <small>per month</small>
            </span>
            <button type="button" className="btn btn-primary" onClick={() => setApplyFor(u)}>
              Apply
            </button>
          </li>
        ))}
      </ul>

      <Modal open={!!applyFor} onClose={() => setApplyFor(null)} title="Apply for this unit">
        {applyFor && <ApplyForm unit={applyFor} onClose={() => setApplyFor(null)} />}
      </Modal>
    </>
  )
}
