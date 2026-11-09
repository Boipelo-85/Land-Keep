import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import './automation.css'

const kinds = ['rent_reminder', 'maintenance_received', 'maintenance_new', 'maintenance_status',
  'maintenance_followup', 'tenant_reply']
const statuses = ['sent', 'delivered', 'read', 'failed', 'skipped']
const label = (value) => value.replaceAll('_', ' ')
const time = (value) => new Date(value).toLocaleString()

export function AutomationLog() {
  const [data, setData] = useState(null)
  const [filters, setFilters] = useState({})
  const [error, setError] = useState('')

  const refresh = async () => setData(await api.automationLog(filters))

  useEffect(() => {
    let active = true
    api.automationLog(filters).then((log) => {
      if (active) setData(log)
    }).catch((err) => {
      if (active) setError(err.message)
    })
    return () => { active = false }
  }, [filters])

  function filter(key, value) {
    setFilters((current) => {
      const next = { ...current }
      if (value) next[key] = value
      else delete next[key]
      return next
    })
  }

  return (
    <section className="automation-page">
      <h1>Notification log</h1>
      <p>Review automated reminders, maintenance updates and tenant replies.</p>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div className="automation-fields">
            <label>Tenant <select value={filters.tenant_id || ''} onChange={(e) => filter('tenant_id', e.target.value)}>
              <option value="">All tenants</option>
              {data.tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
            </select></label>
            {[['kind', 'Type', kinds], ['channel', 'Channel', ['whatsapp', 'sms', 'email', 'none']],
              ['status', 'Status', statuses]].map(([key, name, values]) => (
              <label key={key}>{name} <select value={filters[key] || ''} onChange={(e) => filter(key, e.target.value)}>
                <option value="">All</option>
                {values.map((value) => <option key={value} value={value}>{label(value)}</option>)}
              </select></label>
            ))}
            <button type="button" className="btn btn-secondary"
              onClick={() => refresh().catch((err) => setError(err.message))}>Refresh</button>
          </div>
          {!data.messages.length ? <p>No messages match these filters.</p> :
            <div className="automation-table">
              <table>
                <thead><tr><th>Time</th><th>Tenant</th><th>Message</th><th>Channel</th><th>Status</th></tr></thead>
                <tbody>{data.messages.map((row) => (
                  <tr key={row.id}>
                    <td>{time(row.created_at)}</td>
                    <td>{row.tenant}</td>
                    <td><strong>{row.subject || label(row.kind)}</strong><br />{row.body}</td>
                    <td>{row.channel}<br /><small>{label(row.mode)}</small></td>
                    <td>{row.status}{row.error && <><br /><small>{row.error}</small></>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>}
        </>
      )}
    </section>
  )
}
