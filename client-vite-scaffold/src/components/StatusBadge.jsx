import { STATUS, statusLabel } from '../utils/format'

export default function StatusBadge({ status, role }) {
  const tone = STATUS[status]?.tone || 'neutral'
  return <span className={`badge badge-${tone}`}>{statusLabel(status, role)}</span>
}
