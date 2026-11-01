import { createAsyncThunk } from '@reduxjs/toolkit'

// createAsyncThunk that rejects with a plain message string the UI can show.
export function apiThunk(type, call) {
  return createAsyncThunk(type, async (arg, { rejectWithValue }) => {
    try {
      return await call(arg)
    } catch (e) {
      return rejectWithValue(e.message || 'Something went wrong')
    }
  })
}

// Message from a thunk's .unwrap() error (a string) or a normal Error.
export function errorText(e) {
  return typeof e === 'string' ? e : e?.message || 'Something went wrong'
}
