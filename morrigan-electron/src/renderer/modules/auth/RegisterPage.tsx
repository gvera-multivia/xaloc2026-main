import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/core/auth/auth.store'
import { apiClient } from '@/core/api/client'
import { AUTH } from '@/core/api/endpoints'
import { UserSessionSchema } from '@/core/api/schemas'
import { morriganWs } from '@/core/api/ws'

export function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const { setSession } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      const regRes = await apiClient.post(AUTH.REGISTER, { email, password })
      const userData = regRes.data?.user
      if (!userData) throw new Error('No user in register response')
      const session = UserSessionSchema.parse(userData)
      setSession(session)
      morriganWs.connect()
      window.morrigan.auth.notifyLoginSuccess()
      navigate('/')
    } catch (err: any) {
      const status = err.response?.status
      const detail = err.response?.data?.detail
      if (status === 401) {
        setError('Correo o contraseña no coinciden con XVIA.')
      } else if (status === 409) {
        setError(detail || 'Ese usuario ya existe.')
      } else if (!status) {
        setError(`Error interno local: ${err.message}`)
      } else {
        setError(detail || `Error del servidor (${status}).`)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card fade-in">
        <div className="login-brand">
          <div className="login-eye">●</div>
          <h1 className="login-title">MORRIGAN</h1>
          <p className="login-sub text-muted">Registro validado con XVIA</p>
        </div>

        <div className="divider" style={{ margin: '20px 0' }} />

        <form onSubmit={handleSubmit} className="login-form">
          <div className="field">
            <label className="field-label">CORREO XVIA</label>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="correo@empresa.com"
              autoComplete="email"
              required
              autoFocus
            />
          </div>

          <div className="field">
            <label className="field-label">CONTRASEÑA XVIA</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              required
            />
          </div>

          {error && (
            <div className="login-error">
              <span className="badge badge-red">{error}</span>
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', justifyContent: 'center' }}
            disabled={loading}
          >
            {loading ? <span className="spinner" /> : 'REGISTRARME'}
          </button>

          <button
            type="button"
            className="btn btn-ghost"
            style={{ width: '100%', justifyContent: 'center' }}
            onClick={() => navigate('/login')}
            disabled={loading}
          >
            YA TENGO CUENTA
          </button>
        </form>
      </div>

      <style>{`
        .login-page {
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100vh;
          background: var(--color-raven);
          background-image:
            radial-gradient(ellipse at 20% 50%, rgba(124, 58, 237, 0.04) 0%, transparent 50%),
            radial-gradient(ellipse at 80% 20%, rgba(192, 57, 43, 0.03) 0%, transparent 40%);
        }

        .login-card {
          background: var(--color-obsidian);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-lg);
          padding: 36px 32px;
          width: 360px;
        }

        .login-brand {
          text-align: center;
          margin-bottom: 4px;
        }

        .login-eye {
          font-size: 12px;
          color: var(--color-red);
          margin-bottom: 8px;
          animation: pulse-red 3s ease-in-out infinite;
        }

        .login-title {
          font-size: 1.25rem;
          font-weight: 700;
          letter-spacing: 0.25em;
          margin: 0;
        }

        .login-sub {
          font-size: 0.6875rem;
          letter-spacing: 0.05em;
          margin-top: 4px;
        }

        .login-form {
          display: flex;
          flex-direction: column;
          gap: 14px;
        }

        .field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .field-label {
          font-size: 0.625rem;
          font-weight: 700;
          letter-spacing: 0.12em;
          color: var(--color-text-muted);
        }

        .login-error {
          text-align: center;
        }
      `}</style>
    </div>
  )
}
