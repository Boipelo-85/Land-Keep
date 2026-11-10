import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { ErrorNote, Loading } from '../../components/Feedback'
import { fmtDateTime } from '../../utils/format'

export default function NotificationInbox() {
  const [messages, setMessages] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api.notificationInbox().then((rows) => {
      if (active) setMessages(rows)
    }).catch((err) => {
      if (active) setError(err.message)
    })
    return () => { active = false }
  }, [])

  return (
    <>
      <header className="page-head"><h1>Inbox</h1><p>Read your rent reminders and notices.</p></header>
      <ErrorNote>{error}</ErrorNote>
      {!messages && !error && <Loading />}
      {messages?.length === 0 && <p>No notices yet.</p>}
      {messages?.map((message) => (
        <article className="panel" key={message.id}>
          <h2>{message.subject}</h2>
          <p className="muted small">{fmtDateTime(message.created_at)}</p>
          <p>{message.body}</p>
        </article>
      ))}
    </>
  )
}
