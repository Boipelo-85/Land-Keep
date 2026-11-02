<<<<<<< HEAD
import { useRef, useEffect } from 'react'

export default function Modal({ isOpen, onClose, title, children, actions }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    if (isOpen && dialogRef.current) {
      dialogRef.current.showModal()
    } else if (dialogRef.current) {
      dialogRef.current.close()
    }
  }, [isOpen])

  const handleBackdropClick = (e) => {
    if (e.target === dialogRef.current) {
      onClose()
    }
  }

  if (!isOpen) return null

  return (
    <dialog ref={dialogRef} className="modal" onClick={handleBackdropClick} onCancel={(event) => { event.preventDefault(); onClose() }}>
      <div className="modal-body">
        <div className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        {children}
        {actions && <div className="actions">{actions}</div>}
      </div>
=======
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
>>>>>>> 175b87823ea90111e1ba9f7dabef0492150ad0f5
    </dialog>
  )
}
