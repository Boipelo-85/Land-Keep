import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../services/api'
import { ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import { money, fmtDate } from '../../utils/format'

export default function LandlordPayments() {
  const [data, setData] = useState(null)
  const [enabled, setEnabled] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
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
    return () => { active = false }
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
      <section className="panel"><h2>Tenant balances</h2>{data.charges.length === 0 ? <p>No rent charges yet.</p> : data.charges.map(charge => <article key={charge.charge_id} className="lease"><h3>{charge.tenant} · {charge.property}, {charge.unit}</h3><p>{charge.period} · due {fmtDate(charge.due_date)}</p><p>Charged {money(charge.amount_due)} · Paid {money(charge.amount_paid)} · Outstanding {money(charge.outstanding)}</p></article>)}</section>
      <section className="panel"><h2>Recent payment attempts</h2><p className="muted small">Confirmed payments appear as succeeded. This confirms collection, rather than a bank payout.</p>{data.attempts.length === 0 ? <p>No payment attempts yet.</p> : data.attempts.map(attempt => <article key={attempt.reference}><h3>{attempt.tenant} · {money(attempt.amount)}</h3><p>{attempt.provider} · {attempt.status} · {fmtDate(attempt.created_at)}</p><p className="muted small">{attempt.reference}</p></article>)}</section>
      {data.selected_provider !== 'paystack' && <p><Link to="/landlord/payments/payfast">Previous PayFast settings</Link></p>}
    </>}
  </>
}
