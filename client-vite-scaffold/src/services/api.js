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

async function send(path, { method = 'GET', body, timeoutMs = 30000 } = {}) {
  const headers = {}
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`

  const controller = new AbortController()
  const deadline = setTimeout(() => controller.abort(), timeoutMs)
  let res
  try {
    res = await fetch(BASE + path, {
      method,
      signal: controller.signal,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    })
  } catch (err) {
    if (err.name === 'AbortError') throw new ApiError('The reply took too long. Your message may already be saved; refresh the chat before sending it again.', 408)
    throw new ApiError('Cannot reach the LandKeep server. Is the backend running on port 8000?', 0)
  } finally {
    clearTimeout(deadline)
  }

  if (!res.ok) {
    if (res.status === 401 && authToken && onUnauthorized) onUnauthorized()
    let data = null
    try {
      data = await res.json()
    } catch {
      /* response had no JSON body */
    }
    const fallback = [502, 503, 504].includes(res.status)
      ? 'Cannot reach the LandKeep backend. Start it on port 8000 and check LANDKEEP_API_TARGET in the frontend configuration.'
      : res.statusText || 'Something went wrong'
    throw new ApiError(readDetail(data, fallback), res.status)
  }
  return res
}

const json = async (path, options) => (await send(path, options)).json()

export const api = {
  automationLog: (filters) => json('/automation/log?' + new URLSearchParams(filters)),
  login: (body) => json('/auth/login', { method: 'POST', body }),
  register: (body) => json('/auth/register', { method: 'POST', body }),

  contractors: () => json('/contractors'),
  addContractor: (body) => json('/contractors', { method: 'POST', body }),
  workOrders: () => json('/contractors/work-orders'),
  assignContractor: (id, body) => json(`/contractors/requests/${id}/assign`, { method: 'POST', body }),
  updateWorkOrder: (id, body) => json(`/contractors/work-orders/${id}`, { method: 'PATCH', body }),
  landlordProperties: () => json('/units/properties'),
  createLandlordProperty: (body) => json('/units/properties', { method: 'POST', body }),
  landlordUnits: () => json('/units/mine'),
  createLandlordUnit: (body) => json('/units', { method: 'POST', body }),
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
  myRentPayments: () => json('/payments/mine'),
  createRentCheckout: (chargeId) => json(`/payments/${chargeId}/checkout`, { method: 'POST' }),
  paystackAdmin: () => json('/payments/paystack/admin'),
  savePaystackSettings: (body) => json('/payments/paystack/settings', { method: 'PUT', body }),
  verifyPaystackPayment: (reference) => json('/payments/paystack/verify/' + encodeURIComponent(reference), { method: 'POST' }),
  landlordPaymentSettings: () => json('/payments/settings'),
  saveLandlordPaymentSettings: (body) => json('/payments/settings', { method: 'PUT', body }),
  verifyLandlordPaymentSettings: (body) => json('/payments/settings/verify', { method: 'POST', body }),

  myMaintenance: () => json('/maintenance/mine'),
  reportMaintenance: (formData) => json('/maintenance', { method: 'POST', body: formData }),
  startMaintenanceChat: (body) => json('/maintenance/conversations', { method: 'POST', body }),
  setMaintenancePhotoConsent: (id, consent) => json(`/maintenance/conversations/${id}/photo-consent`, { method: 'POST', body: { consent } }),
  myMaintenanceChats: () => json('/maintenance/conversations/mine'),
  maintenanceChat: (id) => json(`/maintenance/conversations/${id}`),
  sendMaintenanceChat: (id, body) => json(`/maintenance/conversations/${id}/messages`, { method: 'POST', body, timeoutMs: 20000 }),
  resolveMaintenanceChat: (id, body) => json(`/maintenance/conversations/${id}/resolve`, { method: 'POST', body }),
  escalateMaintenanceChat: (id) => json(`/maintenance/conversations/${id}/escalate`, { method: 'POST' }),
  confirmMaintenanceCategory: (id, category) => json(`/maintenance/requests/${id}/classification`, { method: 'PATCH', body: { category } }),
  maintenanceRequests: () => json('/maintenance/requests'),
  updateMaintenanceStatus: (id, status) => json(`/maintenance/requests/${id}/status`, { method: 'PATCH', body: { status } }),

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
  async maintenanceAttachmentUrl(id) {
    const { url } = await json(`/maintenance/attachments/${id}/link`)
    const blob = await (await send(url.replace('/api', ''))).blob()
    return URL.createObjectURL(blob)
  },
}
