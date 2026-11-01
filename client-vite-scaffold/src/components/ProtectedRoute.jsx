import { Navigate, Outlet } from 'react-router-dom'
import { useSelector } from 'react-redux'

// No role: any signed-in user. With a role: only that role, everyone else goes home.
export default function ProtectedRoute({ role }) {
  const user = useSelector((s) => s.auth.user)
  if (!user) return <Navigate to="/login" replace />
  if (role && user.role !== role) return <Navigate to="/" replace />
  return <Outlet />
}
