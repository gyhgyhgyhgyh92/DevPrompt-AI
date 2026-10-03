import { useState } from 'react'

export function SubmitButton({ disabled = false }: { disabled?: boolean }) {
  return (
    <button className="btn btn--submit" data-testid="submit-btn" disabled={disabled}>
      提交
    </button>
  )
}

export function UserTable({ rows }: { rows: Array<{ id: number; name: string }> }) {
  return (
    <table className="user-table">
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td>{r.name}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function LoginForm({ onSubmit }: { onSubmit: (u: string, p: string) => void }) {
  const [error, setError] = useState('')
  return (
    <form className="login-form" onSubmit={(e) => e.preventDefault()}>
      {error && <p className="login-form__error">{error}</p>}
    </form>
  )
}

export function ConfirmModal({ open }: { open: boolean }) {
  if (!open) return null
  return (
    <div className="modal" data-testid="confirm-modal">
      <div className="modal__body">确认执行此操作？</div>
    </div>
  )
}
