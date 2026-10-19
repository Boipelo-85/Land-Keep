import { useEffect, useRef } from 'react'

// Native <dialog>: focus trapping, Escape to close and the backdrop come built in.
export default function Modal({ open, onClose, title, children }) {
  const ref = useRef(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className="modal"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
    >
      {open && (
        <div className="modal-body">
          <header className="modal-head">
            <h2>{title}</h2>
            <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
              &times;
            </button>
          </header>
          {children}
        </div>
      )}
    </dialog>
  )
}
