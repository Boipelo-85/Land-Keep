import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../services/api'
import { ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import { money, fmtDate } from '../../utils/format'

function TenantBalances({ charges, onRecord, onPause, busy }) {
  if (charges.length === 0) return <p>No rent charges yet.</p>
  return (
    <div className="rent-table-wrap" role="region" aria-label="Tenant balances" tabIndex={0}>
      <table className="rent-table">
        <thead>
          <tr>
            <th scope="col">Tenant</th>
            <th scope="col">Property and unit</th>
            <th scope="col">Rent period</th>
            <th scope="col">Due date</th>
            <th scope="col">Charged</th>
            <th scope="col">Paid</th>
            <th scope="col">Balance</th>
            <th scope="col">Status</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {charges.map(charge => (
            <tr key={charge.charge_id}>
              <th scope="row">{charge.tenant}</th>
              <td>{charge.property}, {charge.unit}</td>
              <td>{charge.period}</td>
              <td>{fmtDate(charge.due_date)}</td>
              <td>{money(charge.amount_due, 2)}</td>
              <td>{money(charge.amount_paid, 2)}</td>
              <td>{money(charge.outstanding, 2)}</td>
              <td>{charge.outstanding === 0 ? 'Paid' : charge.amount_paid > 0 ? 'Partially paid' : 'Unpaid'}</td>
              <td>
                {charge.outstanding > 0 && <button className="btn btn-quiet" disabled={busy}
                  onClick={() => onRecord(charge)}>Record payment</button>}
                <button className="btn btn-quiet" disabled={busy} onClick={() => onPause(charge)}>
                  {charge.reminders_paused ? 'Resume reminders' : 'Pause reminders'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function LandlordPayments() {
  const [data, setData] = useState(null)
  const [enabled, setEnabled] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [manual, setManual] = useState(null)
  const load = useCallback(async () => {
    const result = await api.paystackAdmin()
    setData(result)
    setEnabled(result.payments_enabled)
  }, [])
  useEffect(() => {
    let active = true
    api.paystackAdmin().then(result => {
      if (active) { setData(result); setEnabled(result.payments_enabled) }
    }).catch(e => { if (active) setError(e.message) })
    const refresh = setInterval(() => {
      if (document.hidden) return
      api.paystackAdmin().then(result => {
        if (active) setData(result)
      }).catch(() => {})
    }, 15000)
    return () => { active = false; clearInterval(refresh) }
  }, [])
  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await api.savePaystackSettings({ payments_enabled: enabled, current_password: password })
      setPassword('')
      await load()
      setNotice('Payment settings saved.')
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  async function record(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await api.recordManualPayment(manual.charge.charge_id, {
        amount: manual.amount, method: manual.method, request_id: manual.requestId,
      })
      setManual(null)
      await load()
      setNotice('Payment recorded.')
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  async function pause(charge) {
    setBusy(true)
    setError('')
    try {
      await api.pauseLeaseReminders(charge.lease_id, !charge.reminders_paused)
      await load()
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  const totals = data?.charges.reduce((sum, charge) => ({
    charged: sum.charged + charge.amount_due,
    paid: sum.paid + charge.amount_paid,
    outstanding: sum.outstanding + charge.outstanding,
  }), { charged: 0, paid: 0, outstanding: 0 })
  return <>
    <header className="page-head"><h1>Rent payments</h1><p>Manage online rent payments and track your tenants’ balances.</p></header>
    <ErrorNote>{error}</ErrorNote><SuccessNote>{notice}</SuccessNote>
    {!data ? (!error && <Loading />) : <>
      <section className="panel">
        <h2>Paystack checkout</h2>
        <p>Rent is collected into the Land-Keep Paystack account. This page shows payments for your properties only.</p>
        <p><strong>Mode:</strong> {data.gateway.mode === 'test' ? 'Test payments' : 'Live payments'} · <strong>Status:</strong> {data.gateway.ready ? 'Ready' : 'Setup incomplete'}</p>
        {data.selected_provider !== 'paystack' && <p className="note">Paystack is not the active gateway yet. The platform administrator must select Paystack in the server configuration.</p>}
        {data.gateway.reason && <p className="note">{data.gateway.reason}</p>}
        <form onSubmit={save}>
          <label className="checkbox-row"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />Allow my tenants to pay rent online</label>
          <label htmlFor="paystack-password">Confirm with your password</label>
          <input id="paystack-password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} />
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save payment settings'}</button>
        </form>
        <p className="muted small">Card details are entered on Paystack. Secret keys are managed by the platform administrator.</p>
      </section>
      <section className="panel"><h2>Rent overview</h2><dl className="facts"><div><dt>Total charged</dt><dd>{money(totals.charged)}</dd></div><div><dt>Paid</dt><dd>{money(totals.paid)}</dd></div><div><dt>Outstanding</dt><dd>{money(totals.outstanding)}</dd></div></dl><button className="btn btn-secondary" onClick={() => load().catch(e => setError(e.message))}>Refresh payments</button></section>
      <section className="panel">
        <h2>Tenant balances</h2>
        {manual && <form className="inline-form" onSubmit={record}>
          <p>Record payment for {manual.charge.tenant} · {manual.charge.period}</p>
          <label className="field">Amount (R)
            <input type="number" min="0.01" max={manual.charge.outstanding} step="0.01" required
              value={manual.amount} onChange={(e) => setManual({ ...manual, amount: e.target.value })} />
          </label>
          <label className="field">Method
            <select value={manual.method} onChange={(e) => setManual({ ...manual, method: e.target.value })}>
              <option value="cash">Cash</option><option value="eft">Bank transfer</option>
            </select>
          </label>
          <button type="submit" className="btn btn-primary" disabled={busy}>Save payment</button>
          <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => setManual(null)}>Cancel</button>
        </form>}
        <TenantBalances charges={data.charges} busy={busy} onPause={pause} onRecord={(charge) =>
          setManual({ charge, amount: String(charge.outstanding), method: 'cash', requestId: crypto.randomUUID() })} />
      </section>
      <section className="panel"><h2>Recent payment attempts</h2><p className="muted small">Checkout attempts appear here when a tenant continues to the payment provider. Confirmed payments appear as succeeded and update the tenant balance.</p>{data.attempts.length === 0 ? <p>No payment attempts yet.</p> : data.attempts.map(attempt => <article key={attempt.reference}><h3>{attempt.tenant} · {money(attempt.amount)}</h3><p>{attempt.provider} · {attempt.status} · {fmtDate(attempt.created_at)}</p><p className="muted small">{attempt.reference}</p></article>)}</section>
      {data.selected_provider !== 'paystack' && <p><Link to="/landlord/payments/payfast">Previous PayFast settings</Link></p>}
    </>}
  </>
}
