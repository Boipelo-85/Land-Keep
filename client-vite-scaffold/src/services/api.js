// Every call to the FastAPI backend goes through here.
const BASE = '/api'

let authToken = null
let onUnauthorized = null

export function setAuthToken(token) {
  authToken = token
}

// The store registers a handler so an expired login sends the user back to the login page.
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

function readDetail(data, fallback) {
  const d = data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => `${e.loc?.[e.loc.length - 1] ?? 'field'}: ${e.msg}`).join('. ')
  return fallback
}

async function send(path, { method = 'GET', body } = {}) {
  const headers = {}
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`

  let res
  try {
    res = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    })
  } catch {
    throw new ApiError('Cannot reach the LandKeep server. Is the backend running on port 8000?', 0)
  }

  if (!res.ok) {
    if (res.status === 401 && authToken && onUnauthorized) onUnauthorized()
    let data = null
    try {
      data = await res.json()
    } catch {
      /* response had no JSON body */
    }
    throw new ApiError(readDetail(data, res.statusText || 'Something went wrong'), res.status)
  }
  return res
}

const json = async (path, options) => (await send(path, options)).json()

export const api = {
  login: (body) => json('/auth/login', { method: 'POST', body }),
  register: (body) => json('/auth/register', { method: 'POST', body }),

  vacantUnits: () => json('/units/vacant'),

  submitApplication: (body) => json('/applications', { method: 'POST', body }),
  myApplications: () => json('/applications/mine'),
  listApplications: () => json('/applications'),
  getApplication: (id) => json(`/applications/${id}`),
  creditCheck: (id) => json(`/applications/${id}/credit-check`, { method: 'POST' }),
  decide: (id, body) => json(`/applications/${id}/decision`, { method: 'POST', body }),
  convert: (id, body) => json(`/applications/${id}/convert`, { method: 'POST', body }),

  myLeases: () => json('/leases/mine'),
  acceptLease: (id) => json(`/leases/${id}/accept`, { method: 'POST' }),

  myMaintenance: () => json('/maintenance/mine'),
  reportMaintenance: (formData) => json('/maintenance', { method: 'POST', body: formData }),

  // The PDF route needs the login token, so fetch it and save it as a file.
  async downloadLeasePdf(id) {
    const blob = await (await send(`/leases/${id}/pdf`)).blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `lease_${id}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },

  // Photos need the login token, so fetch as a blob URL for <img>.
  async maintenancePhotoUrl(id) {
    const blob = await (await send(`/maintenance/${id}/photo`)).blob()
    return URL.createObjectURL(blob)
  },
}
