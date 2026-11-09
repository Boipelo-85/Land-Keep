import { Navigate, Route, Routes } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { fetchMyLeases, selectHasActiveLease } from './store/leasesSlice'
import { ErrorNote, Loading } from './components/Feedback'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Units from './pages/tenant/Units'
import MyApplications from './pages/tenant/MyApplications'
import ApplicationDetail from './pages/tenant/ApplicationDetail'
import MyLease from './pages/tenant/MyLease'
import Report from './pages/tenant/Report'
import LandlordContractors from './pages/landlord/LandlordContractors'
import LandlordUnits from './pages/landlord/LandlordUnits'
import LandlordApplications from './pages/landlord/LandlordApplications'
import LandlordMaintenance from './pages/landlord/LandlordMaintenance'
import PayRent from './pages/tenant/PayRent'
import LandlordPaymentSettings from './pages/landlord/LandlordPaymentSettings'
import LandlordPayments from './pages/landlord/LandlordPayments'
import { AutomationLog } from './pages/landlord/Automation'

function Home() {
  const user = useSelector((s) => s.auth.user)
  return <Navigate to={user.role === 'landlord' ? '/landlord/applications' : '/units'} replace />
}

function ApplicantUnits() {
  const dispatch = useDispatch()
  const hasActiveLease = useSelector(selectHasActiveLease)
  const { status, error } = useSelector((s) => s.leases)

  if (hasActiveLease) return <Navigate to="/lease" replace />
  if (status === 'failed') return (
    <>
      <ErrorNote>{error}</ErrorNote>
      <button type="button" className="btn btn-secondary" onClick={() => dispatch(fetchMyLeases())}>Try again</button>
    </>
  )
  if (status !== 'ready') return <Loading>Checking your lease</Loading>
  return <Units />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Home />} />

          <Route element={<ProtectedRoute role="tenant" />}>
            <Route path="units" element={<ApplicantUnits />} />
            <Route path="applications" element={<MyApplications />} />
            <Route path="applications/:id" element={<ApplicationDetail />} />
            <Route path="lease" element={<MyLease />} />
            <Route path="report" element={<Report />} />
            <Route path="pay-rent" element={<PayRent />} />
          </Route>

          <Route element={<ProtectedRoute role="landlord" />}>
            <Route path="landlord/contractors" element={<LandlordContractors />} />
            <Route path="landlord/units" element={<LandlordUnits />} />
            <Route path="landlord/applications/:id?" element={<LandlordApplications />} />
            <Route path="landlord/maintenance" element={<LandlordMaintenance />} />
            <Route path="landlord/payments" element={<LandlordPayments />} />
            <Route path="landlord/automation" element={<AutomationLog />} />
            <Route path="landlord/payments/payfast" element={<LandlordPaymentSettings />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
