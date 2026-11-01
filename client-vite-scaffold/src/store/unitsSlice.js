import { createSlice } from '@reduxjs/toolkit'
import { api } from '../services/api'
import { loggedOut } from './authSlice'
import { apiThunk } from './helpers'

export const fetchVacantUnits = apiThunk('units/fetchVacant', () => api.vacantUnits())

const initialState = { items: [], status: 'idle', error: null }

export default createSlice({
  name: 'units',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loggedOut, () => initialState)
      .addCase(fetchVacantUnits.pending, (state) => {
        state.status = 'loading'
        state.error = null
      })
      .addCase(fetchVacantUnits.fulfilled, (state, { payload }) => {
        state.status = 'ready'
        state.items = payload
      })
      .addCase(fetchVacantUnits.rejected, (state, { payload, error }) => {
        state.status = 'failed'
        state.error = payload || error.message
      })
  },
}).reducer
