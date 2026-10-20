import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { Empty, ErrorNote, Loading } from '../../components/Feedback'

const STATUS_OPTIONS = ['received', 'in_progress', 'awaiting_parts', 'resolved']

export default function LandlordMaintenance() {
  const [requests, setRequests] = useState([])
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState('')
  async function load() {
    setStatus('loading'); setError('')
    try { setRequests(await api.maintenanceRequests()); setStatus('ready') }
    catch (err) { setError(err.message); setStatus('failed') }
  }
  useEffect(() => { load() }, [])
  async function changeStatus(id, next) {
    try { await api.updateMaintenanceStatus(id, next); await load() }
    catch (err) { setError(err.message) }
  }

  return <>
    <header className="page-head"><h1>Maintenance requests</h1><p>Chat reports are scoped to your agency and sorted by urgency.</p></header>
    <ErrorNote>{error}</ErrorNote>
    {status === 'loading' && <Loading />}
    {status === 'ready' && requests.length === 0 && <Empty title="No maintenance requests">Tenant reports to your agency will appear here.</Empty>}
    {requests.map((request) => <article key={request.id} className="panel maint-item">
      <header className="lease-head"><div><h2>{request.property}, unit {request.unit}</h2><p className="muted small">{request.tenant} · MR-{String(request.id).padStart(6, '0')}</p></div>
        <span className={`badge ${request.urgency === 'emergency' || request.urgency === 'high' ? 'badge-bad' : request.urgency ? 'badge-warn' : 'badge-neutral'}`}>{request.urgency || request.status}</span></header>
      <p><strong>{request.summary || request.description}</strong></p>
      {request.category && <p>Category: {request.category.replaceAll('_', ' ')} · likely cause: {request.likely_cause || 'Not assessed'}</p>}
      {request.tried_self_help && <details><summary>Chat and self-help details</summary><pre className="chat-transcript">{request.tried_self_help}</pre></details>}
      {request.conversation?.messages?.flatMap((message) => message.attachments || []).map((photo) => <LandlordPhoto key={photo.id} photo={photo} />)}
      <label className="field"><span>Request status</span><select value={request.status === 'open' ? 'received' : request.status} onChange={(event) => changeStatus(request.id, event.target.value)}>
        {STATUS_OPTIONS.map((option) => <option key={option} value={option}>{option.replaceAll('_', ' ')}</option>)}
      </select></label>
    </article>)}
  </>
}

function LandlordPhoto({ photo }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let objectUrl
    let cancelled = false
    api.maintenanceAttachmentUrl(photo.id).then((url) => {
      if (cancelled) { URL.revokeObjectURL(url); return }
      objectUrl = url; setSrc(url)
    }).catch(() => {})
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [photo.id])
  return src ? <img className="maint-photo" src={src} alt="Tenant maintenance photo" /> : null
}
