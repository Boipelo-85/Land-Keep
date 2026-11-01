import { configureStore } from '@reduxjs/toolkit'
import { setUnauthorizedHandler } from '../services/api'
import authReducer, { logout } from './authSlice'
import unitsReducer from './unitsSlice'
import applicationsReducer from './applicationsSlice'
import leasesReducer from './leasesSlice'
import maintenanceReducer from './maintenanceSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    units: unitsReducer,
    applications: applicationsReducer,
    leases: leasesReducer,
    maintenance: maintenanceReducer,
  },
})

// If the server says the login expired, drop the session and the router sends us to /login.
setUnauthorizedHandler(() => store.dispatch(logout()))
