type ConfirmModalProps = {
  message: string
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmModal({ message, onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Confirm action">
      <div className="modal-box">
        <p className="modal-message">{message}</p>
        <div className="modal-actions">
          <button className="save-btn" onClick={onConfirm} autoFocus>
            Confirm
          </button>
          <button className="secondary-btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
