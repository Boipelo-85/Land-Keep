import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import Modal from '../../components/Modal'

export default function LandlordPaymentSettings() {
  const [merchantId, setMerchantId] = useState('')
  const [savedMerchantId, setSavedMerchantId] = useState(null)
  const [verificationStatus, setVerificationStatus] = useState('not_verified')
  const [paymentsEnabled, setPaymentsEnabled] = useState(false)
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [showSaveConfirm, setShowSaveConfirm] = useState(false)
  const [savePrompt, setSavePrompt] = useState('')
  const [nextIdToSave, setNextIdToSave] = useState('')
  const [showVerifyConfirm, setShowVerifyConfirm] = useState(false)

  async function refreshSettings(initial = false) {
    const data = await api.landlordPaymentSettings()
    setSavedMerchantId(data.payfast_merchant_id_masked)
    setVerificationStatus(data.verification_status)
    if (initial) setPaymentsEnabled(data.payments_enabled)
  }

  useEffect(() => {
    refreshSettings(true).catch((e) => setError(e.message)).finally(() => setLoading(false))
    const timer = window.setInterval(() => refreshSettings().catch(() => {}), 5000)
    return () => window.clearInterval(timer)
  }, [])

  async function save(event) {
    event.preventDefault()
    setSaving(true)
    setSaved(false)
    setError('')
    try {
      if (!password) throw new Error('Enter your password to confirm this change.')
      const nextId = merchantId.trim()
      const prompt = nextId
        ? 'Save this PayFast merchant ID? Changing it disables tenant payments until the new account is verified.'
        : 'Save these payment settings?'
      setSavePrompt(prompt)
      setNextIdToSave(nextId)
      setShowSaveConfirm(true)
    } catch (e) {
      setError(e.message)
      setSaving(false)
    }
  }

  async function confirmSave() {
    setShowSaveConfirm(false)
    try {
      const data = await api.saveLandlordPaymentSettings({
        payfast_merchant_id: nextIdToSave || null,
        current_password: password,
        payments_enabled: paymentsEnabled,
      })
      setSavedMerchantId(data.payfast_merchant_id_masked)
      setVerificationStatus(data.verification_status)
      setPaymentsEnabled(data.payments_enabled)
      setMerchantId('')
      setPassword('')
      setSaved(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function verifyAccount() {
    setError('')
    setSaved(false)
    try {
      if (!password) throw new Error('Enter your password to confirm the R5.00 test payment.')
      setShowVerifyConfirm(true)
    } catch (e) {
      setError(e.message)
    }
  }

  async function confirmVerify() {
    setShowVerifyConfirm(false)
    try {
      const checkout = await api.verifyLandlordPaymentSettings({ current_password: password })
      const form = document.createElement('form')
      form.method = 'POST'
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
    }
  }

  return (
    <>
      <header className="page-head">
        <h1>Online rent payments</h1>
        <p>Connect the PayFast merchant account that should receive rent from your tenants.</p>
      </header>
      {loading ? <Loading /> : (
        <section className="panel">
          <h2>Your PayFast recipient account</h2>
          <p className="muted">Enter the 8 digit merchant ID from your own PayFast account. Find it on the merchant settings page of your PayFast dashboard. Sandbox and live merchant IDs are separate, so use the ID for the configured PayFast mode.</p>
          <ErrorNote>{error}</ErrorNote>
          <SuccessNote>{saved ? 'PayFast payment settings saved.' : ''}</SuccessNote>
          <form className="payment-settings-form" onSubmit={save}>
            {savedMerchantId && <p><strong>Saved merchant ID:</strong> {savedMerchantId}</p>}
            <label htmlFor="payfast-merchant-id">{savedMerchantId ? 'New merchant ID (leave blank to keep current)' : 'PayFast merchant ID'}</label>
            <input id="payfast-merchant-id" inputMode="numeric" autoComplete="off" maxLength={8} pattern="[0-9]{8}" value={merchantId} onChange={(event) => { setMerchantId(event.target.value); if (event.target.value) setPaymentsEnabled(false) }} placeholder="8 digits" />
            <label htmlFor="payment-settings-password">Confirm with your password</label>
            <input id="payment-settings-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <label className="checkbox-row">
              <input type="checkbox" checked={paymentsEnabled} disabled={verificationStatus !== 'verified'} onChange={(event) => setPaymentsEnabled(event.target.checked)} />
              Allow tenants to pay rent online
            </label>
            <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save payment settings'}</button>
          </form>
          <p><strong>Account status:</strong> {verificationStatus === 'verified' ? 'Verified' : 'Not verified'}</p>
          {verificationStatus !== 'verified' && savedMerchantId && (
            <button className="btn btn-secondary" type="button" onClick={verifyAccount}>Verify account with R5.00 test payment</button>
          )}
          <p className="muted small">{verificationStatus === 'verified' ? 'PayFast confirmed the verification payment.' : 'Tenant payments stay disabled until PayFast confirms the R5.00 verification payment.'} Land-Keep never collects or stores card numbers.</p>
          <p className="muted small">This is a real R5.00 transaction in the selected PayFast mode.</p>
        </section>
      )}
      <Modal
        isOpen={showSaveConfirm}
        onClose={() => { setShowSaveConfirm(false); setSaving(false) }}
        title="Confirm"
        actions={
          <>
            <button className="btn btn-modal-secondary" onClick={() => { setShowSaveConfirm(false); setSaving(false) }}>
              Cancel
            </button>
            <button className="btn btn-modal-primary" onClick={confirmSave}>
              OK
            </button>
          </>
        }
      >
        <p>{savePrompt}</p>
      </Modal>
      <Modal
        isOpen={showVerifyConfirm}
        onClose={() => setShowVerifyConfirm(false)}
        title="Confirm"
        actions={
          <>
            <button className="btn btn-modal-secondary" onClick={() => setShowVerifyConfirm(false)}>
              Cancel
            </button>
            <button className="btn btn-modal-primary" onClick={confirmVerify}>
              OK
            </button>
          </>
        }
      >
        <p>Continue to PayFast to make a R5.00 account verification payment?</p>
      </Modal>
    </>
  )
}
