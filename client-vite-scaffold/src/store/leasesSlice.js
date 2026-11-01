import { createSlice } from '@reduxjs/toolkit'
import { api } from '../services/api'
import { loggedOut } from './authSlice'
import { apiThunk } from './helpers'

export const fetchMyLeases = apiThunk('leases/fetchMine', () => api.myLeases())
export const acceptLease = apiThunk('leases/accept', (id) => api.acceptLease(id))

const initialState = { items: [], status: 'idle', error: null }

export default createSlice({
  name: 'leases',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loggedOut, () => initialState)
      .addCase(fetchMyLeases.pending, (state) => {
        state.status = 'loading'
        state.error = null
      })
      .addCase(fetchMyLeases.fulfilled, (state, { payload }) => {
        state.status = 'ready'
        state.items = payload
      })
      .addCase(fetchMyLeases.rejected, (state, { payload, error }) => {
        state.status = 'failed'
        state.error = payload || error.message
      })
      .addCase(acceptLease.fulfilled, (state, { payload }) => {
        const i = state.items.findIndex((l) => l.id === payload.id)
        if (i >= 0) state.items[i] = payload
      })
  },
}).reducer
