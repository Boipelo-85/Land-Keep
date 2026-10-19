import { createSlice } from '@reduxjs/toolkit'
import { api } from '../services/api'
import { loggedOut } from './authSlice'
import { apiThunk } from './helpers'

export const fetchApplications = apiThunk('applications/fetchAll', (role) =>
  role === 'landlord' ? api.listApplications() : api.myApplications(),
)
export const fetchApplication = apiThunk('applications/fetchOne', (id) => api.getApplication(id))
export const submitApplication = apiThunk('applications/submit', (body) => api.submitApplication(body))
export const runCreditCheck = apiThunk('applications/creditCheck', (id) => api.creditCheck(id))
export const decideApplication = apiThunk('applications/decide', ({ id, decision, note }) =>
  api.decide(id, { decision, note: note || null }),
)
export const convertApplication = apiThunk('applications/convert', async ({ id, ...body }) => {
  const lease = await api.convert(id, body)
  const application = await api.getApplication(id)
  return { lease, application }
})

const initialState = { items: [], status: 'idle', error: null }

// Update an application in place, or add it. Detail calls add `timeline`; list calls do not.
function upsert(state, application) {
  const i = state.items.findIndex((a) => a.id === application.id)
  if (i >= 0) state.items[i] = { ...state.items[i], ...application }
  else state.items.unshift(application)
}

export default createSlice({
  name: 'applications',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loggedOut, () => initialState)
      .addCase(fetchApplications.pending, (state) => {
        state.status = 'loading'
        state.error = null
      })
      .addCase(fetchApplications.fulfilled, (state, { payload }) => {
        state.status = 'ready'
        const old = new Map(state.items.map((a) => [a.id, a]))
        state.items = payload.map((a) => ({ ...old.get(a.id), ...a }))
      })
      .addCase(fetchApplications.rejected, (state, { payload, error }) => {
        state.status = 'failed'
        state.error = payload || error.message
      })
      .addCase(convertApplication.fulfilled, (state, { payload }) => upsert(state, payload.application))
    for (const thunk of [fetchApplication, submitApplication, runCreditCheck, decideApplication]) {
      builder.addCase(thunk.fulfilled, (state, { payload }) => upsert(state, payload))
    }
  },
}).reducer
