import { useEffect, useState } from 'react'
import { api } from '../../services/api'
import { ErrorNote, Loading } from '../../components/Feedback'

export default function LandlordContractors() {
  const [contractors, setContractors] = useState([])
  const [requests, setRequests] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [person, setPerson] = useState({name:'',trade:'plumbing',phone:'',email:''})
  const [assignment, setAssignment] = useState({request_id:'',contractor_id:'',scheduled_for:'',notes:''})
  const field = (setter,key) => (event) => setter((value) => ({...value,[key]:event.target.value}))
  async function refresh() {
    const [people,reports,work] = await Promise.all([api.contractors(),api.maintenanceRequests(),api.workOrders()])
    setContractors(people);setRequests(reports);setOrders(work)
  }
  useEffect(() => { refresh().catch((err)=>setError(err.message)).finally(()=>setLoading(false)) }, [])
  async function add(event) {
    event.preventDefault();if(busy)return
    setBusy(true);setError('');setNotice('')
    try { const row=await api.addContractor(person);setContractors((rows)=>[...rows,row]);setPerson({name:'',trade:'plumbing',phone:'',email:''});setNotice('Contractor saved. Coordinate visits with them directly.') }
    catch(err){setError(err.message)}finally{setBusy(false)}
  }
  async function assign(event) {
    event.preventDefault();if(busy)return
    setBusy(true);setError('');setNotice('')
    try { await api.assignContractor(assignment.request_id,{contractor_id:Number(assignment.contractor_id),scheduled_for:assignment.scheduled_for||null,notes:assignment.notes});await refresh();setNotice('Work order saved. The tenant can see the assignment in their maintenance chat.') }
    catch(err){setError(err.message)}finally{setBusy(false)}
  }
  async function status(order,next) {
    setBusy(true);setError('')
    try { await api.updateWorkOrder(order.id,{status:next,scheduled_for:order.scheduled_for,notes:order.notes||''});await refresh() }
    catch(err){setError(err.message)}finally{setBusy(false)}
  }
  if(loading)return <Loading/>
  return <>
    <header className="page-head"><h1>Contractors and work orders</h1><p>Save your tradespeople, assign a maintenance report and track the work. Contact contractors directly to confirm availability.</p></header>
    <ErrorNote>{error}</ErrorNote>{notice&&<p className="success-note" role="status">{notice}</p>}
    <section className="panel"><h2>Add contractor</h2><form onSubmit={add}>
      <label className="field"><span>Name or company</span><input required minLength={2} maxLength={120} value={person.name} onChange={field(setPerson,'name')}/></label>
      <label className="field"><span>Trade</span><select value={person.trade} onChange={field(setPerson,'trade')}>{['plumbing','electrical','security','general'].map(x=><option key={x} value={x}>{x}</option>)}</select></label>
      <label className="field"><span>Phone</span><input maxLength={40} value={person.phone} onChange={field(setPerson,'phone')}/></label>
      <label className="field"><span>Email</span><input type="email" maxLength={160} value={person.email} onChange={field(setPerson,'email')}/></label>
      <button className="btn btn-primary" disabled={busy}>Save contractor</button>
    </form></section>
    <section className="panel"><h2>Assign maintenance</h2>{contractors.length===0?<p>Add a contractor first.</p>:<form onSubmit={assign}>
      <label className="field"><span>Maintenance report</span><select required value={assignment.request_id} onChange={field(setAssignment,'request_id')}><option value="">Choose a report</option>{requests.filter(x=>x.status!=='resolved').map(x=><option key={x.id} value={x.id}>MR-{String(x.id).padStart(6,'0')} · {x.property} {x.unit} · {(x.primary_issue||x.description).slice(0,70)}</option>)}</select></label>
      <label className="field"><span>Contractor</span><select required value={assignment.contractor_id} onChange={field(setAssignment,'contractor_id')}><option value="">Choose contractor</option>{contractors.map(x=><option key={x.id} value={x.id}>{x.name} · {x.trade}</option>)}</select></label>
      <label className="field"><span>Visit date (optional)</span><input type="date" value={assignment.scheduled_for} onChange={field(setAssignment,'scheduled_for')}/></label>
      <label className="field"><span>Work notes</span><textarea maxLength={2000} value={assignment.notes} onChange={field(setAssignment,'notes')}/></label>
      <button className="btn btn-primary" disabled={busy}>Create work order</button>
    </form>}</section>
    <section className="panel"><h2>Your contractors</h2>{contractors.map(x=><p key={x.id}><strong>{x.name}</strong> · {x.trade} · {x.phone||'No phone'} · {x.email||'No email'}</p>)}{!contractors.length&&<p>No contractors saved.</p>}</section>
    <h2>Work orders</h2>{orders.length===0&&<p>No work orders yet.</p>}{orders.map(order=><article className="panel" key={order.id}>
      <h3>{order.contractor_name} · MR-{String(order.request_id).padStart(6,'0')}</h3><p>{order.scheduled_for||'Visit date to be arranged'}</p><p>{order.notes}</p>
      <label className="field"><span>Work status</span><select disabled={busy||['completed','cancelled'].includes(order.status)} value={order.status} onChange={(e)=>status(order,e.target.value)}>{['assigned','scheduled','in_progress','completed','cancelled'].map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}</select></label>
    </article>)}
  </>
}
