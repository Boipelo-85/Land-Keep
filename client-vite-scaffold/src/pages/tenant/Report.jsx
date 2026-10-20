import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { fetchMyLeases } from '../../store/leasesSlice'
import { fetchMyMaintenance } from '../../store/maintenanceSlice'
import { api } from '../../services/api'
import { Empty, ErrorNote, Loading } from '../../components/Feedback'
import StatusBadge from '../../components/StatusBadge'
import { fmtDateTime } from '../../utils/format'

export default function Report() {
  const dispatch = useDispatch()
  const leases = useSelector((s) => s.leases)
  const maintenance = useSelector((s) => s.maintenance)
  const activeLease = leases.items.find((lease) => lease.status === 'active')
  const [conversation, setConversation] = useState(null)
  const [text, setText] = useState('')
  const [photos, setPhotos] = useState([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef(null)

  useEffect(() => { dispatch(fetchMyLeases()); dispatch(fetchMyMaintenance()) }, [dispatch])

  async function start() {
    setBusy(true); setError('')
    try { setConversation(await api.startMaintenanceChat({ lease_id: activeLease.id, photo_sharing_consent: consent })) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function refresh() {
    if (!conversation) return
    setConversation(await api.maintenanceChat(conversation.id))
  }

  async function sendMessage(event) {
    event.preventDefault()
    if (!text.trim() && photos.length === 0) return
    const data = new FormData()
    data.append('text', text.trim())
    photos.forEach((photo) => data.append('photos', photo))
    setBusy(true); setError('')
    try {
      setConversation(await api.sendMaintenanceChat(conversation.id, data))
      setText(''); setPhotos([]); if (fileRef.current) fileRef.current.value = ''
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function resolve(solved) {
    setBusy(true); setError('')
    try { setConversation(await api.resolveMaintenanceChat(conversation.id, { solved, answer: solved ? 'Yes' : 'No or unsure' })) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function escalate() {
    setBusy(true); setError('')
    try { setConversation(await api.escalateMaintenanceChat(conversation.id)) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  if (leases.status === 'loading' || leases.status === 'idle') return <Loading />
  if (!activeLease) return <Empty title="You need an active lease">Check <Link to="/lease">My lease</Link> if you are waiting to accept one.</Empty>

  return <>
    <header className="page-head"><h1>Maintenance help</h1><p>Describe the problem and LandKeep will help you decide what to do next.</p></header>
    {!conversation ? <section className="panel maint-form">
      <h2>{activeLease.property}, unit {activeLease.unit}</h2>
      <p className="muted">You can share photos so the AI helper and your landlord can assess the issue. Photos are stored privately.</p>
      <label className="field"><span><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I understand photos I upload will be shared with my landlord and Anthropic's AI service.</span></label>
      <ErrorNote>{error}</ErrorNote>
      <button className="btn btn-primary" disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Start chat'}</button>
    </section> : <section className="panel maintenance-chat">
      <header className="lease-head"><div><h2>{activeLease.property}, unit {activeLease.unit}</h2><p className="muted small">Chat status: {conversation.status.replaceAll('_', ' ')}</p></div>
        <button className="btn btn-secondary" onClick={escalate} disabled={busy || conversation.request_id}>Report to landlord</button></header>
      <div className="chat-messages" aria-live="polite">
        {conversation.messages.map((message) => <article key={message.id} className={`chat-bubble ${message.role === 'tenant' ? 'chat-mine' : 'chat-bot'}`}>
          <p>{message.text}</p>
          {message.attachments?.map((attachment) => <ChatPhoto key={attachment.id} attachment={attachment} />)}
        </article>)}
        {busy && <p className="muted">LandKeep is checking this…</p>}
      </div>
      <ErrorNote>{error}</ErrorNote>
      {conversation.status === 'open' && <>
        <form className="chat-compose" onSubmit={sendMessage}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} rows={3} placeholder="Tell us what happened…" aria-label="Your message" />
          <input ref={fileRef} type="file" multiple accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" capture="environment" onChange={(e) => setPhotos(Array.from(e.target.files || []))} />
          <small>Up to 5 JPG, PNG or WEBP photos, 5 MB each.</small>
          {photos.length > 0 && <small>{photos.length} photo(s) selected</small>}
          <button className="btn btn-primary" disabled={busy || (!text.trim() && photos.length === 0)}>{busy ? 'Sending…' : 'Send'}</button>
        </form>
        {conversation.messages.some((message) => message.role === 'bot' && message.text.includes('Did that solve it?')) && <div className="actions">
          <button className="btn btn-secondary" disabled={busy} onClick={() => resolve(true)}>Yes, it is solved</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => resolve(false)}>No / not sure</button>
        </div>}
      </>}
      {conversation.request_id && <p className="success-note">Your landlord has the report. Reference MR-{String(conversation.request_id).padStart(6, '0')}.</p>}
      {conversation.status === 'resolved_self_help' && <p className="success-note">Marked as resolved by self-help.</p>}
    </section>}

    <header className="page-head"><h2>My reports</h2></header>
    {maintenance.status === 'loading' && <Loading />}
    {maintenance.status === 'ready' && maintenance.items.length === 0 && <Empty title="No reports yet">When you send a report to your landlord, it appears here.</Empty>}
    {maintenance.items.map((req) => <article key={req.id} className="panel maint-item"><header className="lease-head"><div><h2>{req.property}, unit {req.unit_number}</h2><p className="muted small">Sent {fmtDateTime(req.created_at)}</p></div><StatusBadge status={req.status} /></header><p>{req.description}</p></article>)}
  </>
}

function ChatPhoto({ attachment }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let objectUrl
    let cancelled = false
    api.maintenanceAttachmentUrl(attachment.id).then((url) => {
      if (cancelled) { URL.revokeObjectURL(url); return }
      objectUrl = url; setSrc(url)
    }).catch(() => {})
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [attachment.id])
  return src ? <img className="maint-photo" src={src} alt="Photo attached to maintenance chat" /> : null
}
