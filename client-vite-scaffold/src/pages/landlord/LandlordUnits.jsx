import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { Empty, ErrorNote, Loading } from '../../components/Feedback'
import { money } from '../../utils/format'

const blankProperty = { name: '', address: '', city: '' }
const blankUnit = { property_id: '', unit_number: '', bedrooms: '1', monthly_rent: '' }

export default function LandlordUnits() {
  const [properties, setProperties] = useState([])
  const [units, setUnits] = useState([])
  const [propertyForm, setPropertyForm] = useState(blankProperty)
  const [unitForm, setUnitForm] = useState(blankUnit)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([api.landlordProperties(), api.landlordUnits()]).then(([props, rows]) => {
      if (cancelled) return
      setProperties(props); setUnits(rows)
      setUnitForm((form) => ({ ...form, property_id: props[0] ? String(props[0].id) : '' }))
    }).catch((err) => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const update = (setter, key) => (event) => setter((form) => ({ ...form, [key]: event.target.value }))

  async function addProperty(event) {
    event.preventDefault()
    if (busy) return
    setBusy('property'); setError(''); setNotice('')
    try {
      const property = await api.createLandlordProperty(propertyForm)
      setProperties((rows) => [...rows, property])
      setUnitForm((form) => ({ ...form, property_id: String(property.id) }))
      setPropertyForm(blankProperty)
      setNotice(`Property ${property.name} added. You can now add its units below.`)
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  async function addUnit(event) {
    event.preventDefault()
    if (busy) return
    setBusy('unit'); setError(''); setNotice('')
    try {
      const unit = await api.createLandlordUnit({ ...unitForm, property_id: Number(unitForm.property_id),
        bedrooms: Number(unitForm.bedrooms), monthly_rent: Number(unitForm.monthly_rent) })
      setUnits((rows) => [...rows, unit])
      setUnitForm((form) => ({ ...blankUnit, property_id: form.property_id }))
      setNotice(`Unit ${unit.unit_number} is listed. Tenants can find it under Find a unit and apply.`)
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  return <>
    <header className="page-head"><h1>My units</h1><p>Add a property, then list its vacant units for tenants to apply.</p></header>
    <ErrorNote>{error}</ErrorNote>
    {notice && <p className="success-note" role="status">{notice}</p>}
    {loading ? <Loading /> : <>
      <section className="panel">
        <h2>Add property</h2>
        <form onSubmit={addProperty}>
          <label className="field"><span>Property name</span><input required minLength={2} maxLength={120} value={propertyForm.name} onChange={update(setPropertyForm, 'name')} /></label>
          <label className="field"><span>Street address</span><input required minLength={3} maxLength={200} value={propertyForm.address} onChange={update(setPropertyForm, 'address')} /></label>
          <label className="field"><span>City</span><input required minLength={2} maxLength={80} value={propertyForm.city} onChange={update(setPropertyForm, 'city')} /></label>
          <button className="btn btn-secondary" disabled={Boolean(busy)}>{busy === 'property' ? 'Adding…' : 'Add property'}</button>
        </form>
      </section>
      <section className="panel">
        <h2>Add unit</h2>
        {properties.length === 0 ? <p>Add your first property above before listing a unit.</p> : <form onSubmit={addUnit}>
          <label className="field"><span>Property</span><select required value={unitForm.property_id} onChange={update(setUnitForm, 'property_id')}>
            <option value="">Select a property</option>{properties.map((property) => <option key={property.id} value={property.id}>{property.name} — {property.city}</option>)}
          </select></label>
          <label className="field"><span>Unit number</span><input required maxLength={20} value={unitForm.unit_number} onChange={update(setUnitForm, 'unit_number')} placeholder="e.g. A01" /></label>
          <label className="field"><span>Bedrooms (0 for studio)</span><input required type="number" min="0" max="20" step="1" value={unitForm.bedrooms} onChange={update(setUnitForm, 'bedrooms')} /></label>
          <label className="field"><span>Monthly rent (R)</span><input required type="number" min="0.01" max="100000000" step="0.01" value={unitForm.monthly_rent} onChange={update(setUnitForm, 'monthly_rent')} /></label>
          <p className="muted small">New units are listed as vacant immediately. Units reserved by a pending or active lease are hidden from available listings.</p>
          <button className="btn btn-primary" disabled={Boolean(busy)}>{busy === 'unit' ? 'Publishing…' : 'Publish unit'}</button>
        </form>}
      </section>
      <header className="page-head"><h2>Your units</h2></header>
      {units.length === 0 && <Empty title="No units yet">Publish your first unit using the form above.</Empty>}
      {units.map((unit) => <article key={unit.id} className="panel">
        <h3>{unit.property}, unit {unit.unit_number}</h3>
        <p>{unit.address}, {unit.city}</p>
        <p>{unit.bedrooms === 0 ? 'Studio' : `${unit.bedrooms} bedroom${unit.bedrooms === 1 ? '' : 's'}`} · {money(unit.monthly_rent)} per month</p>
        <span className={`badge ${unit.listed_for_applications ? 'badge-ok' : 'badge-neutral'}`}>{unit.listed_for_applications ? 'Listed for applications' : 'Occupied or reserved'}</span>
      </article>)}
    </>}
  </>
}
