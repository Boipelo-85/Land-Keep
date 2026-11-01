import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../../services/api'
import { ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import Modal from '../../components/Modal'
import { fmtDate, money } from '../../utils/format'

export default function PayRent() {
  const location = useLocation()
  const [data, setData] = useState({ charges: [], attempts: [] })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await api.myRentPayments())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function pay(charge) {
    setBusy(charge.charge_id)
    setError('')
    try {
      const checkout = await api.createRentCheckout(charge.charge_id)
      const form = document.createElement('form')
      form.method = 'POST'
      const destination = new URL(checkout.action)
      if (!['sandbox.payfast.co.za', 'www.payfast.co.za'].includes(destination.hostname) || destination.protocol !== 'https:') throw new Error('Invalid payment destination')
      form.action = checkout.action
      Object.entries(checkout.fields).forEach(([name, value]) => {
        const input = document.createElement('input')
        input.type = 'hidden'
        input.name = name
        input.value = value
        form.appendChild(input)
      })
      document.body.appendChild(form)
      form.submit()
    } catch (e) {
      setError(e.message)
      setBusy(null)
    }
  }

  const outcome = new URLSearchParams(location.search).get('payment')

  return (
    <>
      <header className="page-head">
        <h1>Pay rent</h1>
        <p>Pay an outstanding rent charge securely online. Your balance updates after PayFast confirms the payment.</p>
      </header>
      {outcome === 'return' && <SuccessNote>PayFast returned you to LandKeep. We’re checking the payment confirmation; refresh in a moment if your balance has not updated.</SuccessNote>}
      {outcome === 'cancelled' && <p className="muted">Payment was cancelled. Your rent balance is unchanged.</p>}
      {!selected && <ErrorNote>{error}</ErrorNote>}
      {loading ? <Loading /> : data.charges.length === 0 ? (
        <section className="panel"><h2>You’re all caught up</h2><p className="muted">There are no outstanding rent charges on your active leases.</p></section>
      ) : data.charges.map((charge) => (
        <article className="panel lease" key={charge.charge_id}>
          <header className="lease-head">
            <div><h2>{charge.property}, unit {charge.unit}</h2><p className="muted">{charge.period} rent · due {fmtDate(charge.due_date)}</p></div>
            <span className="badge badge-brand">Outstanding {money(charge.outstanding)}</span>
          </header>
          <dl className="facts"><div><dt>Rent charged</dt><dd>{money(charge.amount_due)}</dd></div><div><dt>Paid so far</dt><dd>{money(charge.amount_paid)}</dd></div></dl>
          <button className="btn btn-primary" type="button" disabled={busy !== null} onClick={() => { setSelected(charge); setError('') }}>
            {busy === charge.charge_id ? 'Opening secure checkout…' : `Pay ${money(charge.outstanding)} securely`}
          </button>
          <p className="muted small">Checkout is handled securely by PayFast. LandKeep records the payment only after PayFast confirms it.</p>
        </article>
      ))}
      <Modal isOpen={Boolean(selected)} onClose={() => { if (busy === null) setSelected(null) }} title="Secure rent checkout">
        {selected && <>
          <p>{selected.property}, unit {selected.unit} · {selected.period}</p>
          <h2>{money(selected.outstanding)}</h2>
          <p>You will enter your card details or choose an available bank-payment method on PayFast's secure checkout page.</p>
          <p className="muted small">Available methods depend on your merchant account and device. LandKeep does not collect your card number, security code, bank password, or PIN.</p>
          {selected.checkout?.mode === 'sandbox' && <p className="note">Sandbox mode: use only PayFast test payment details.</p>}
          {!selected.checkout?.ready && <p className="note note-bad" role="alert">{selected.checkout?.reason || 'Payment setup is incomplete. Ask your landlord to finish Payment setup.'}</p>}
          <ErrorNote>{error}</ErrorNote>
          <div className="actions">
            <button className="btn btn-quiet" disabled={busy !== null} onClick={() => setSelected(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={busy !== null || !selected.checkout?.ready} onClick={() => pay(selected)}>{busy !== null ? 'Opening PayFast…' : 'Continue to PayFast'}</button>
          </div>
        </>}
      </Modal>
      {data.attempts.length > 0 && <section className="panel"><h2>Recent payment attempts</h2>{data.attempts.map((attempt) => <p key={attempt.reference}>{attempt.reference} · {money(attempt.amount)} · {attempt.status}</p>)}</section>}
    </>
  )
}
