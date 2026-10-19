import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { fetchMyLeases } from '../../store/leasesSlice'
import { fetchMyMaintenance, reportMaintenance } from '../../store/maintenanceSlice'
import { errorText } from '../../store/helpers'
import { api } from '../../services/api'
import { Empty, ErrorNote, Loading, SuccessNote } from '../../components/Feedback'
import StatusBadge from '../../components/StatusBadge'
import { fmtDateTime } from '../../utils/format'

function RequestPhoto({ id }) {
  const [src, setSrc] = useState('')

  useEffect(() => {
    let url = ''
    let cancelled = false
    api.maintenancePhotoUrl(id).then((u) => {
      if (cancelled) {
        URL.revokeObjectURL(u)
        return
      }
      url = u
      setSrc(u)
    })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [id])

  if (!src) return null
  return <img className="maint-photo" src={src} alt="Attached to this report" />
}

export default function Report() {
  const dispatch = useDispatch()
  const leases = useSelector((s) => s.leases)
  const { items, status, error } = useSelector((s) => s.maintenance)

  const [description, setDescription] = useState('')
  const [photo, setPhoto] = useState(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [notice, setNotice] = useState('')

  const activeLease = leases.items.find((l) => l.status === 'active')
  const leasesReady = leases.status === 'ready' || leases.status === 'failed'

  useEffect(() => {
    dispatch(fetchMyLeases())
    dispatch(fetchMyMaintenance())
  }, [dispatch])

  useEffect(() => {
    if (!photo) {
      setPreview('')
      return
    }
    const url = URL.createObjectURL(photo)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [photo])

  async function submit(e) {
    e.preventDefault()
    setFormError('')
    setNotice('')
    const text = description.trim()
    if (text.length < 5) return setFormError('Describe the problem in at least 5 characters.')
    if (text.length > 1000) return setFormError('Keep the description to 1000 characters or fewer.')

    const formData = new FormData()
    formData.append('description', text)
    if (photo) formData.append('photo', photo)

    setBusy(true)
    try {
      await dispatch(reportMaintenance(formData)).unwrap()
      setDescription('')
      setPhoto(null)
      setNotice('Problem reported. An acknowledgement was sent by email and SMS.')
    } catch (err) {
      setFormError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <header className="page-head">
        <h1>Report a problem</h1>
        <p>Tell us what is wrong in your unit. You can attach a photo if it helps.</p>
      </header>

      {!leasesReady && <Loading />}
      {leasesReady && !activeLease && (
        <Empty title="You need an active lease">
          You can report a problem once you have an active lease. Check{' '}
          <Link to="/lease">My lease</Link> if you are waiting to accept one.
        </Empty>
      )}

      {activeLease && (
        <form className="panel maint-form" onSubmit={submit}>
          <h2>
            {activeLease.property}, unit {activeLease.unit}
          </h2>
          <p className="muted small">Reports go against this active lease.</p>

          <label className="field">
            <span>What is the problem?</span>
            <textarea
              rows={4}
              maxLength={1000}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              placeholder="For example: water dripping under the kitchen sink"
            />
            <small>{description.trim().length} / 1000</small>
          </label>

          <label className="field">
            <span>Photo (optional)</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
              onChange={(e) => setPhoto(e.target.files?.[0] || null)}
            />
            <small>Jpg, png, or webp. Maximum 5 MB.</small>
          </label>

          {preview && <img className="maint-photo" src={preview} alt="Preview of the photo you chose" />}

          <ErrorNote>{formError}</ErrorNote>
          <SuccessNote>{notice}</SuccessNote>

          <div className="actions actions-start">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? 'Sending' : 'Send report'}
            </button>
          </div>
        </form>
      )}

      <header className="page-head">
        <h2>My reports</h2>
      </header>
      {status === 'loading' && items.length === 0 && <Loading />}
      <ErrorNote>{status === 'failed' ? error : ''}</ErrorNote>
      {status === 'ready' && items.length === 0 && (
        <Empty title="No reports yet">When you send a report, it appears here.</Empty>
      )}
      {items.map((req) => (
        <article key={req.id} className="panel maint-item">
          <header className="lease-head">
            <div>
              <h2>
                {req.property}, unit {req.unit_number}
              </h2>
              <p className="muted small">Sent {fmtDateTime(req.created_at)}</p>
            </div>
            <StatusBadge status={req.status} />
          </header>
          <p>{req.description}</p>
          {req.has_photo && <RequestPhoto id={req.id} />}
        </article>
      ))}
    </>
  )
}
