import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { fmtDate, money } from '../../utils/format'
import './automation.css'

const kinds = ['rent_reminder', 'maintenance_received', 'maintenance_new', 'maintenance_status',
  'maintenance_followup', 'tenant_reply', 'preference_changed']
const statuses = ['queued', 'sent', 'delivered', 'read', 'failed', 'skipped', 'recorded']
const label = (value) => value.replaceAll('_', ' ')
const time = (value) => new Date(value).toLocaleString()

function ReminderSettings() {
  const [policy, setPolicy] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [usage, setUsage] = useState(null)
  const [properties, setProperties] = useState([])
  const [forecast, setForecast] = useState(null)
  const [forecastBusy, setForecastBusy] = useState(false)

  useEffect(() => {
    let active = true
    api.reminderPolicy().then((result) => {
      if (active) setPolicy(result)
    }).catch((err) => {
      if (active) setError(err.message)
    })
    api.reminderUsage().then((result) => {
      if (active) setUsage(result)
    }).catch((err) => {
      if (active) setError(err.message)
    })
    api.reminderProperties().then((result) => {
      if (active) setProperties(result)
    }).catch((err) => {
      if (active) setError(err.message)
    })
    return () => { active = false }
  }, [])

  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      setPolicy(await api.saveReminderPolicy(policy))
      setUsage(await api.reminderUsage())
      setForecast(null)
      setMessage('Reminder settings saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function estimate() {
    setForecastBusy(true)
    setError('')
    try {
      setForecast(await api.reminderCostPreview())
    } catch (err) {
      setError(err.message)
    } finally {
      setForecastBusy(false)
    }
  }

  function toggleStep(offset, channel, checked) {
    const selected = policy.steps[offset] || ([3, 0, -3].includes(offset) ? ['email', 'sms', 'whatsapp'] : ['email'])
    setPolicy({ ...policy, steps: { ...policy.steps,
      [offset]: checked ? [...selected, channel] : selected.filter((item) => item !== channel) } })
  }

  function updateProperty(id, channel, value) {
    const override = { ...policy.properties[id] }
    if (value === 'inherit') delete override[channel]
    else override[channel] = value === 'true'
    setPolicy({ ...policy, properties: { ...policy.properties, [id]: override } })
  }

  const cost = (values) => Object.entries(values).map(([currency, value]) =>
    `${currency} ${Number(value).toFixed(2)}`).join(' · ') || 'No priced messages'

  return (
    <section className="panel">
      <h2>Reminder settings</h2>
      <p>The in-app inbox stays on. Paid channels are available only to tenants who opt in.</p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {policy && <form onSubmit={save}>
        <fieldset disabled={busy}>
          <legend>Delivery controls</legend>
          {[['reminders_enabled', 'Automatic rent reminders'], ['sms', 'Enable SMS'], ['whatsapp', 'Enable WhatsApp']]
            .map(([key, name]) => <label className="checkbox-row" key={key}>
              <input type="checkbox" checked={policy[key]} onChange={(event) =>
                setPolicy({ ...policy, [key]: event.target.checked })} />
              {name}
            </label>)}
        </fieldset>
        {properties.length > 0 && <details>
          <summary>Property channel overrides</summary>
          {properties.map((property) => (
            <fieldset key={property.id} disabled={busy}>
              <legend>{property.name}</legend>
              {['sms', 'whatsapp'].map((channel) => (
                <label key={channel} className="field">
                  <span>{channel === 'sms' ? 'SMS' : 'WhatsApp'}</span>
                  <select value={String(policy.properties[property.id]?.[channel] ?? 'inherit')}
                    onChange={(event) => updateProperty(property.id, channel, event.target.value)}>
                    <option value="inherit">Use landlord setting</option>
                    <option value="true">Enabled</option>
                    <option value="false">Disabled</option>
                  </select>
                </label>
              ))}
            </fieldset>
          ))}
        </details>}
        <label className="field">
          <span>Monthly paid message cap</span>
          <input type="number" min="0" max="1000000" required value={policy.monthly_message_cap}
            onChange={(event) => setPolicy({ ...policy, monthly_message_cap: Number(event.target.value) })} />
          <small>SMS and WhatsApp share this cap. Zero blocks paid delivery.</small>
        </label>
        <fieldset disabled={busy}>
          <legend>Reminder schedule</legend>
          {[3, 1, 0, -1, -3, -7].map((offset) => (
            <div key={offset}>
              <label className="checkbox-row">
                <input type="checkbox" checked={policy.offsets.includes(offset)}
                  onChange={(event) => setPolicy({ ...policy, offsets: event.target.checked
                    ? [...policy.offsets, offset] : policy.offsets.filter((item) => item !== offset) })} />
                {offset === 0 ? 'On the due date' : `${Math.abs(offset)} day(s) ${offset > 0 ? 'before' : 'overdue'}`}
              </label>
              {policy.offsets.includes(offset) && ['email', 'sms', 'whatsapp'].map((channel) => (
                <label className="checkbox-row" key={channel}>
                  <input type="checkbox" checked={(policy.steps[offset] ||
                    ([3, 0, -3].includes(offset) ? ['email', 'sms', 'whatsapp'] : ['email'])).includes(channel)}
                    onChange={(event) => toggleStep(offset, channel, event.target.checked)} />
                  {channel}
                </label>
              ))}
            </div>
          ))}
        </fieldset>
        <label className="field">
          <span>Custom message template</span>
          <textarea rows={3} maxLength={600} value={policy.template}
            onChange={(event) => setPolicy({ ...policy, template: event.target.value })} />
          <small>{'Variables: {tenant_name}, {amount}, {due_date}, {unit}, {property}'}</small>
        </label>
        <button className="btn btn-primary" disabled={busy}>Save reminder settings</button>
      </form>}
      <h3>Messaging this month</h3>
      {usage && <p>{usage.used} of {usage.cap} paid messages reserved ({usage.percentage}%) · {cost(usage.estimated)}</p>}
      {usage && <ul>{Object.entries(usage.counts).map(([channel, count]) => <li key={channel}>{label(channel)} · {count}</li>)}</ul>}
      <button type="button" className="btn btn-secondary" disabled={forecastBusy} onClick={estimate}>
        {forecastBusy ? 'Estimating…' : 'Preview 30-day costs'}
      </button>
      {forecast && <p>{Object.entries(forecast.counts).map(([channel, count]) => `${channel} · ${count}`).join(' / ') ||
        'No eligible paid reminders'} · {forecast.demo ? 'Demo delivery is free' : cost(forecast.estimated)}</p>}
    </section>
  )
}

function RentReminderPreview({ onSimulate }) {
  const [date, setDate] = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function run(event) {
    event.preventDefault()
    setBusy(true)
    setPreview(null)
    setError('')
    setMessage('')
    try {
      const result = await api.previewRentReminders(date)
      if (result.summary.agency_errors.length) throw new Error('Could not evaluate rent reminders.')
      setPreview(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function simulate() {
    setBusy(true)
    setError('')
    try {
      const result = await api.simulateRentReminders(date)
      if (result.summary.agency_errors.length) throw new Error('Could not simulate rent reminders.')
      await onSimulate()
      setMessage('Simulation complete. Check the inbox and notification log for the demo messages.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Automatic rent reminders</h2>
      <p>The applicant suggests a payment date. When they accept the lease, LandKeep checks the agreed due date and
        outstanding balance. It sends reminders automatically through the channels the tenant has opted into.</p>
      <p>Preview who would get a reminder on a given day. Leave the date blank to check today.
        Previewing sends no messages.</p>
      <form className="automation-fields" onSubmit={run}>
        <label>Preview date <input type="date" value={date} disabled={busy}
          onChange={(event) => { setDate(event.target.value); setPreview(null) }} /></label>
        <button className="btn btn-secondary" disabled={busy}>{busy ? 'Checking…' : 'Preview reminders'}</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {preview && (
        <div aria-live="polite">
          {preview.demo_landlord && !preview.can_simulate && <p>Demo landlord accounts can preview reminders only.</p>}
          {preview.can_simulate && date && <button className="btn btn-secondary" type="button"
            disabled={busy} onClick={simulate}>Run demo simulation</button>}
          {preview.reminders.length === 0 ? <p>No new reminders match this date.</p> :
            <ul>{preview.reminders.map((row) => (
              <li key={`${row.tenant_id}-${row.period}-${row.window_days}`}>
                <strong>{row.tenant}</strong>
                {row.leases.map((lease) => (
                  <div key={lease.lease_id}>{lease.property}, {lease.unit} · Due {fmtDate(lease.due_date)} · {money(lease.amount_outstanding, 2)} outstanding</div>
                ))}
                <small>{row.channels.map((channel) =>
                  channel.status === 'would_send' ? `Would send by ${channel.channel}` :
                    channel.skip_reason || channel.error || label(channel.status)).join(' · ')}</small>
              </li>
            ))}</ul>}
        </div>
      )}
    </section>
  )
}

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
      <ReminderSettings />
      <RentReminderPreview onSimulate={refresh} />
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div className="automation-fields">
            <label>Tenant <select value={filters.tenant_id || ''} onChange={(e) => filter('tenant_id', e.target.value)}>
              <option value="">All tenants</option>
              {data.tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
            </select></label>
            {[['kind', 'Type', kinds], ['channel', 'Channel', ['in_app', 'whatsapp', 'sms', 'email', 'none']],
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
                    <td><strong>{row.subject || label(row.kind)}</strong><br />
                      {row.channel === 'whatsapp' && row.mode === 'log'
                        ? <p className="simulated-whatsapp">{row.body}</p> : row.body}
                    </td>
                    <td>{row.channel}<br /><small>{label(row.mode)}</small></td>
                    <td>{row.status}{row.error && <><br /><small>{row.error}</small></>}
                      {row.cost_estimate != null && <><br /><small>Estimated {row.cost_currency} {row.cost_estimate}</small></>}
                      {row.actual_cost != null && <><br /><small>Actual {row.actual_cost_currency} {row.actual_cost}</small></>}
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>}
        </>
      )}
    </section>
  )
}
