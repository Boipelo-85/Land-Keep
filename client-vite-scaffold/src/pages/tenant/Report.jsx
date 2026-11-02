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
  const messageEndRef = useRef(null)
  const inputRef = useRef(null)
  const sendingRef = useRef(false)
  const [pendingText, setPendingText] = useState('')
  const resumeChecked = useRef(false)

  useEffect(() => { dispatch(fetchMyLeases()); dispatch(fetchMyMaintenance()) }, [dispatch])

  useEffect(() => {
    if (leases.status !== 'ready' || !activeLease || conversation || resumeChecked.current) return
    resumeChecked.current = true
    api.myMaintenanceChats().then((items) => {
      const current = items.find((item) => item.lease_id === activeLease.id && (item.status === 'open' || item.status === 'escalated'))
      if (current) setConversation(current)
    }).catch((err) => setError(err.message))
  }, [leases.status, activeLease, conversation])

  useEffect(() => {
    if (conversation?.id) dispatch(fetchMyMaintenance())
  }, [dispatch, conversation?.id, conversation?.request_id, conversation?.status])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [conversation?.messages.length, pendingText, busy])

  async function start() {
    setBusy(true); setError('')
    try { setConversation(await api.startMaintenanceChat({ lease_id: activeLease.id, photo_sharing_consent: consent })) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function sendMessage(event) {
    event.preventDefault()
    if (sendingRef.current || busy || (!text.trim() && photos.length === 0)) return
    sendingRef.current = true
    setPendingText(text.trim() || 'Photo attached')
    const data = new FormData()
    data.append('text', text.trim())
    photos.forEach((photo) => data.append('photos', photo))
    setBusy(true); setError('')
    try {
      setConversation(await api.sendMaintenanceChat(conversation.id, data))
      setText(''); setPhotos([]); if (fileRef.current) fileRef.current.value = ''
    } catch (err) { setError(err.message) }
    finally {
      sendingRef.current = false; setPendingText(''); setBusy(false)
      inputRef.current?.focus()
    }
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      sendMessage(event)
    }
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

  async function changePhotoConsent(value) {
    setBusy(true); setError('')
    try {
      setConversation(await api.setMaintenancePhotoConsent(conversation.id, value))
      if (!value) { setPhotos([]); if (fileRef.current) fileRef.current.value = '' }
    }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  if (leases.status === 'loading' || leases.status === 'idle') return <Loading />
  if (leases.status === 'failed') return <ErrorNote>{leases.error || 'Could not load your lease. Please try again.'}</ErrorNote>
  if (!activeLease) return <Empty title="You need an active lease">Maintenance chat becomes available once your application is approved and your lease is active. Check <Link to="/lease">My lease</Link> for your lease status.</Empty>

  return <>
    <header className="page-head"><h1>Maintenance help</h1><p>Describe the problem and LandKeep will help you decide what to do next.</p></header>
    {!conversation ? <section className="panel maint-form">
      <h2>{activeLease.property}, unit {activeLease.unit}</h2>
      <p className="muted">You can share photos so the AI helper and your landlord can assess the issue. Photos are stored privately.</p>
      <label className="field"><span><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /> I understand photos I upload will be shared with my landlord and Google's Gemini AI service (free-tier submissions may help improve Google products).</span></label>
      <ErrorNote>{error}</ErrorNote>
      <button className="btn btn-primary" disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Start chat'}</button>
    </section> : <section className="panel maintenance-chat">
      <header className="lease-head"><div><h2>{activeLease.property}, unit {activeLease.unit}</h2><p className="muted small">Chat status: {conversation.status.replaceAll('_', ' ')}</p></div>
        <button className="btn btn-secondary" onClick={escalate} disabled={busy || Boolean(conversation.request_id) || conversation.status === 'resolved_self_help'}>Report to landlord</button></header>
      <p className="muted small" role="status">{conversation.assistant_mode === 'trained_local' ? 'Using fast local complaint guidance.' : conversation.assistant_mode === 'instant' ? 'Ready to help with your maintenance question.' : conversation.assistant_mode === 'local'
        ? 'Using local guidance. Live AI is unavailable; you can still chat and report issues.'
        : 'AI assistance enabled. You can continue chatting after reporting an issue.'}</p>
      <div className="chat-messages" aria-live="polite" aria-busy={Boolean(pendingText)}>
        {conversation.messages.map((message) => <article key={message.id} className={`chat-bubble ${message.role === 'tenant' ? 'chat-mine' : 'chat-bot'}`}>
          <p>{message.text}</p>
          {message.attachments?.map((attachment) => <ChatPhoto key={attachment.id} attachment={attachment} />)}
        </article>)}
        {pendingText && <article className="chat-bubble chat-mine"><p>{pendingText}</p></article>}
        {pendingText && <p className="muted" role="status">LandKeep is replying…</p>}
        <div ref={messageEndRef} />
      </div>
      <ErrorNote>{error}</ErrorNote>
      {(conversation.status === 'open' || conversation.status === 'escalated') && <>
        <form className="chat-compose" onSubmit={sendMessage}>
          <textarea ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={handleKeyDown} maxLength={2000} rows={3} placeholder="Tell us what happened… (Press Enter to send, Shift+Enter for new line)" aria-label="Your message" />
          <button className="btn btn-primary" disabled={busy || (!text.trim() && photos.length === 0)}>{pendingText ? 'Sending…' : 'Send message'}</button>
          <details><summary>Attach photos (optional)</summary><label className="field photo-consent"><span><input type="checkbox" checked={Boolean(conversation.photo_sharing_consent)} disabled={busy} onChange={(e) => changePhotoConsent(e.target.checked)} /> I agree to share uploaded photos privately with my landlord and Google's Gemini AI service (free-tier submissions may help improve Google products).</span></label>
          <input ref={fileRef} type="file" multiple disabled={!conversation.photo_sharing_consent || busy} accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" capture="environment" onChange={(e) => setPhotos(Array.from(e.target.files || []))} />
          {!conversation.photo_sharing_consent && <small>Accept the photo sharing notice above to attach photos. You can still send a text message.</small>}
          <small>Up to 5 JPG, PNG or WEBP photos, 5 MB each.</small>
          {photos.length > 0 && <small>{photos.length} photo(s) selected</small>}</details>
        </form>
        {conversation.status === 'open' && conversation.messages.filter((message) => message.role === 'tenant').length > 0 && <div className="actions">
          <button className="btn btn-secondary" disabled={busy} onClick={() => resolve(true)}>Yes, it is solved</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => resolve(false)}>No / not sure</button>
        </div>}
      </>}
      {conversation.priority && <p><strong>Priority: {conversation.priority}</strong> · Your landlord can review this suggestion.</p>}
      {conversation.classification && <p className="muted small">Trained classifier suggestion: {conversation.classification.category}{conversation.classification.needs_review ? ' (needs landlord review)' : ''}. This labels the request; it does not diagnose the fault.</p>}
      {conversation.request_id && <p className="success-note">Your report is saved for your landlord. You can keep chatting here. Reference MR-{String(conversation.request_id).padStart(6, '0')}.</p>}
      {conversation.status === 'resolved_self_help' && <><p className="success-note">Marked as resolved by self-help.</p><button className="btn btn-primary" disabled={busy} onClick={start}>Start a new chat</button></>}
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
