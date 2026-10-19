import { createSlice } from '@reduxjs/toolkit'
import { api } from '../services/api'
import { loggedOut } from './authSlice'
import { apiThunk } from './helpers'

export const fetchMyMaintenance = apiThunk('maintenance/fetchMine', () => api.myMaintenance())
export const reportMaintenance = apiThunk('maintenance/report', (formData) => api.reportMaintenance(formData))

const initialState = { items: [], status: 'idle', error: null }

export default createSlice({
  name: 'maintenance',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loggedOut, () => initialState)
      .addCase(fetchMyMaintenance.pending, (state) => {
        state.status = 'loading'
        state.error = null
      })
      .addCase(fetchMyMaintenance.fulfilled, (state, { payload }) => {
        state.status = 'ready'
        state.items = payload
      })
      .addCase(fetchMyMaintenance.rejected, (state, { payload, error }) => {
        state.status = 'failed'
        state.error = payload || error.message
      })
      .addCase(reportMaintenance.fulfilled, (state, { payload }) => {
        state.items = [payload, ...state.items.filter((r) => r.id !== payload.id)]
      })
  },
}).reducer
