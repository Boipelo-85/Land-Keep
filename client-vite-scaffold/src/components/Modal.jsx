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
    </dialog>
  )
}
