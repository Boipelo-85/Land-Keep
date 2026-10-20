import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { logout } from '../store/authSlice'

const LINKS = {
  landlord: [{ to: '/landlord/applications', label: 'Applications' }, { to: '/landlord/maintenance', label: 'Maintenance' }],
  tenant: [
    { to: '/units', label: 'Find a unit' },
    { to: '/applications', label: 'My applications' },
    { to: '/lease', label: 'My lease' },
    { to: '/report', label: 'Report a problem' },
  ],
}

// Parts of the platform that are designed for but not built yet.
const COMING = {
  landlord: ['Rent', 'Insights'],
  tenant: ['Pay rent'],
}

export default function Layout() {
  const dispatch = useDispatch()
  const navigate = useNavigate()
  const user = useSelector((s) => s.auth.user)

  function signOut() {
    dispatch(logout())
    navigate('/login', { replace: true })
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">LandKeep</div>

        <nav className="nav" aria-label="Main">
          {LINKS[user.role].map((l) => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
              {l.label}
            </NavLink>
          ))}
          {COMING[user.role].map((label) => (
            <span key={label} className="nav-link soon" aria-disabled="true">
              {label}
              <small>soon</small>
            </span>
          ))}
        </nav>

        <div className="who">
          <div className="who-name">{user.full_name}</div>
          <div className="who-role">{user.role === 'landlord' ? 'Landlord' : 'Applicant or tenant'}</div>
          <button type="button" className="link-btn" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
