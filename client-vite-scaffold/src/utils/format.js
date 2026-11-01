// The API sends UTC times without a "Z", so add one before parsing.
export function parseDate(value) {
  if (!value) return null
  if (typeof value === 'string' && value.includes('T') && !/(Z|[+-]\d\d:?\d\d)$/.test(value)) {
    return new Date(`${value}Z`)
  }
  return new Date(value)
}

const isDateOnly = (v) => typeof v === 'string' && v.length === 10

export function fmtDate(value) {
  const d = parseDate(value)
  if (!d) return '-'
  return new Intl.DateTimeFormat('en-ZA', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...(isDateOnly(value) ? { timeZone: 'UTC' } : {}),
  }).format(d)
}

export function fmtDateTime(value) {
  const d = parseDate(value)
  if (!d) return '-'
  return new Intl.DateTimeFormat('en-ZA', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
}

export const money = (n) =>
  `R ${Number(n).toLocaleString('en-ZA', { maximumFractionDigits: 0 })}`

export const percent = (ratio) => `${Math.round(ratio * 100)}%`

// Application statuses: label, colour tone, and what an applicant sees instead of "Rejected".
export const STATUS = {
  submitted: { label: 'Submitted', tone: 'neutral' },
  under_review: { label: 'In review', tone: 'warn' },
  approved: { label: 'Approved', tone: 'ok' },
  rejected: { label: 'Rejected', tone: 'bad', tenantLabel: 'Not successful' },
  lease_issued: { label: 'Lease issued', tone: 'brand' },
  active_tenant: { label: 'Active tenant', tone: 'ok' },
  open: { label: 'Open', tone: 'warn' },
  in_progress: { label: 'In progress', tone: 'brand' },
  resolved: { label: 'Resolved', tone: 'ok' },
}

export function statusLabel(status, role) {
  const s = STATUS[status]
  if (!s) return status
  return role === 'tenant' && s.tenantLabel ? s.tenantLabel : s.label
}
