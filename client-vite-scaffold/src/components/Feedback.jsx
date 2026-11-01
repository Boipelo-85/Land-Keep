export function ErrorNote({ children }) {
  if (!children) return null
  return (
    <p className="note note-bad" role="alert">
      {children}
    </p>
  )
}

export function SuccessNote({ children }) {
  if (!children) return null
  return (
    <p className="note note-ok" role="status">
      {children}
    </p>
  )
}

export function Loading({ children = 'Loading' }) {
  return (
    <p className="muted" role="status">
      {children}...
    </p>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  )
}
