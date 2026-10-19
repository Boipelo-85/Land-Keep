import { createSlice } from '@reduxjs/toolkit'
import { api, setAuthToken } from '../services/api'
import { apiThunk } from './helpers'

const KEY = 'landkeep_session'

function loadSession() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY))
    if (saved?.token && saved?.user) {
      setAuthToken(saved.token)
      return saved
    }
  } catch {
    /* no saved session */
  }
  return { token: null, user: null }
}

function saveSession(session) {
  setAuthToken(session.token)
  try {
    localStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    /* storage unavailable: the login just will not survive a refresh */
  }
}

export const login = apiThunk('auth/login', async (credentials) => {
  const session = await api.login(credentials)
  saveSession(session)
  return session
})

export const register = apiThunk('auth/register', async (details) => {
  const session = await api.register(details)
  saveSession(session)
  return session
})

const slice = createSlice({
  name: 'auth',
  initialState: { ...loadSession(), status: 'idle', error: null },
  reducers: {
    loggedOut(state) {
      state.token = null
      state.user = null
      state.status = 'idle'
      state.error = null
    },
    clearAuthError(state) {
      state.error = null
    },
  },
  extraReducers: (builder) => {
    for (const thunk of [login, register]) {
      builder
        .addCase(thunk.pending, (state) => {
          state.status = 'loading'
          state.error = null
        })
        .addCase(thunk.fulfilled, (state, { payload }) => {
          state.status = 'idle'
          state.token = payload.token
          state.user = payload.user
        })
        .addCase(thunk.rejected, (state, { payload, error }) => {
          state.status = 'idle'
          state.error = payload || error.message
        })
    }
  },
})

export const { loggedOut, clearAuthError } = slice.actions

export const logout = () => (dispatch) => {
  setAuthToken(null)
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
  dispatch(loggedOut())
}

export default slice.reducer
