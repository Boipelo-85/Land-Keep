import { fmtDateTime } from '../utils/format'

// The application tracker: one rail from "received" to "moved in".
const STEPS = [
  { match: ['submitted'], title: 'Application received', waiting: '' },
  { match: ['under_review'], title: 'Credit check and review', waiting: 'The landlord will review it next' },
  { match: ['approved', 'rejected'], title: 'Decision', waiting: 'Waiting for the landlord to decide' },
  { match: ['lease_issued'], title: 'Lease agreement', waiting: 'Issued once the application is approved' },
  { match: ['active_tenant'], title: 'Moved in', waiting: 'After the lease is accepted' },
]

export default function Tracker({ application, audience }) {
  const timeline = application.timeline || []
  const rejected = application.status === 'rejected'
  const steps = rejected ? STEPS.slice(0, 3) : STEPS
  const entryFor = (step) => timeline.find((t) => step.match.includes(t.status))
  // A step with a timestamp is done. The first step without one is what happens next.
  const next = steps.findIndex((step) => !entryFor(step))

  return (
    <ol className="tracker" aria-label="Application progress">
      {steps.map((step, i) => {
        const entry = entryFor(step)
        const state = entry ? 'done' : i === next ? 'current' : 'upcoming'

        let title = step.title
        let tone = ''
        if (i === 2 && entry) {
          if (entry.status === 'approved') title = 'Approved'
          else {
            title = audience === 'tenant' ? 'Not successful' : 'Rejected'
            tone = ' is-bad'
          }
        }
        // Notes are system text, except a landlord's own words after "approved the application: ".
        // Landlords see the system notes that add information. Applicants only see what the landlord wrote.
        let note = ''
        if (entry?.note) {
          const written = entry.note.includes(': ') ? entry.note.split(': ').slice(1).join(': ') : ''
          if (audience === 'tenant') note = i === 2 ? written : ''
          else if (entry.note !== step.title) note = entry.note
        }

        return (
          <li key={step.title} className={`tracker-step is-${state}${tone}`} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="tracker-dot" aria-hidden="true" />
            <div>
              <div className="tracker-title">{title}</div>
              <div className="tracker-meta">{entry ? fmtDateTime(entry.at) : step.waiting}</div>
              {note && <p className="tracker-note">{note}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
