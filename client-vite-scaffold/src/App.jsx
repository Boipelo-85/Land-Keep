import { Navigate, Route, Routes } from 'react-router-dom'
import { useSelector } from 'react-redux'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Units from './pages/tenant/Units'
import MyApplications from './pages/tenant/MyApplications'
import ApplicationDetail from './pages/tenant/ApplicationDetail'
import MyLease from './pages/tenant/MyLease'
import Report from './pages/tenant/Report'
import LandlordApplications from './pages/landlord/LandlordApplications'
import LandlordMaintenance from './pages/landlord/LandlordMaintenance'

function Home() {
  const user = useSelector((s) => s.auth.user)
  return <Navigate to={user.role === 'landlord' ? '/landlord/applications' : '/units'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />

          <Route element={<ProtectedRoute role="tenant" />}>
            <Route path="units" element={<Units />} />
            <Route path="applications" element={<MyApplications />} />
            <Route path="applications/:id" element={<ApplicationDetail />} />
            <Route path="lease" element={<MyLease />} />
            <Route path="report" element={<Report />} />
          </Route>

          <Route element={<ProtectedRoute role="landlord" />}>
            <Route path="landlord/applications/:id?" element={<LandlordApplications />} />
            <Route path="landlord/maintenance" element={<LandlordMaintenance />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
