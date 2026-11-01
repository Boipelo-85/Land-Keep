from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models as m
from ..database import get_db
from ..deps import require_landlord

router = APIRouter(prefix='/contractors', tags=['contractors'])


class ContractorIn(BaseModel):
    model_config = {'str_strip_whitespace': True}
    name: str = Field(min_length=2, max_length=120)
    trade: Literal['plumbing','electrical','security','general']
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)


class AssignmentIn(BaseModel):
    contractor_id: int = Field(gt=0)
    scheduled_for: date | None = None
    notes: str = Field(default='', max_length=2000)


class WorkOrderIn(BaseModel):
    status: Literal['assigned','scheduled','in_progress','completed','cancelled']
    scheduled_for: date | None = None
    notes: str = Field(default='', max_length=2000)


def work_order_out(db, row):
    contractor = db.get(m.Contractor, row.contractor_id)
    return {'id':row.id,'request_id':row.request_id,'contractor_id':row.contractor_id,
            'contractor_name':contractor.name,'trade':contractor.trade,'status':row.status,
            'scheduled_for':row.scheduled_for,'notes':row.notes,'created_at':row.created_at}


def owned_request(db, request_id, agency_id):
    req = db.scalar(select(m.MaintenanceRequest).join(m.Unit).join(m.Property).where(
        m.MaintenanceRequest.id==request_id, m.Property.landlord_id==agency_id))
    if req is None:
        raise HTTPException(404, 'Maintenance request not found')
    return req


@router.get('')
def list_contractors(user: m.User=Depends(require_landlord), db:Session=Depends(get_db)):
    rows=db.scalars(select(m.Contractor).where(m.Contractor.agency_id==user.id).order_by(m.Contractor.name)).all()
    return [{'id':r.id,'name':r.name,'trade':r.trade,'phone':r.phone,'email':r.email} for r in rows]


@router.post('', status_code=201)
def add_contractor(body:ContractorIn,user:m.User=Depends(require_landlord),db:Session=Depends(get_db)):
    row=m.Contractor(agency_id=user.id,**body.model_dump());db.add(row);db.commit()
    return {'id':row.id,'name':row.name,'trade':row.trade,'phone':row.phone,'email':row.email}


@router.post('/requests/{request_id}/assign', status_code=201)
def assign(request_id:int,body:AssignmentIn,user:m.User=Depends(require_landlord),db:Session=Depends(get_db)):
    req=owned_request(db,request_id,user.id)
    if req.status=='resolved':
        raise HTTPException(409,'This maintenance request is already resolved')
    contractor=db.scalar(select(m.Contractor).where(m.Contractor.id==body.contractor_id,m.Contractor.agency_id==user.id))
    if contractor is None:
        raise HTTPException(404,'Contractor not found')
    active=db.scalars(select(m.MaintenanceWorkOrder).where(m.MaintenanceWorkOrder.request_id==request_id,
        m.MaintenanceWorkOrder.status.not_in(['cancelled','completed']))).all()
    for old in active:
        old.status='cancelled'
    row=m.MaintenanceWorkOrder(agency_id=user.id,request_id=request_id,contractor_id=contractor.id,
        scheduled_for=body.scheduled_for,notes=body.notes,status='scheduled' if body.scheduled_for else 'assigned')
    db.add(row)
    if req.conversation_id:
        db.add(m.MaintenanceMessage(conversation_id=req.conversation_id,role='bot',
            text=f'Your landlord assigned {contractor.name} ({contractor.trade}) to this report.' + (f' Scheduled for {body.scheduled_for}.' if body.scheduled_for else ' A visit date has not been set.')))
    db.commit()
    return work_order_out(db,row)


@router.get('/work-orders')
def list_work_orders(user:m.User=Depends(require_landlord),db:Session=Depends(get_db)):
    rows=db.scalars(select(m.MaintenanceWorkOrder).where(m.MaintenanceWorkOrder.agency_id==user.id).order_by(m.MaintenanceWorkOrder.created_at.desc())).all()
    return [work_order_out(db,r) for r in rows]


@router.patch('/work-orders/{work_order_id}')
def update_work_order(work_order_id:int,body:WorkOrderIn,user:m.User=Depends(require_landlord),db:Session=Depends(get_db)):
    row=db.scalar(select(m.MaintenanceWorkOrder).where(m.MaintenanceWorkOrder.id==work_order_id,m.MaintenanceWorkOrder.agency_id==user.id))
    if row is None:
        raise HTTPException(404,'Work order not found')
    req=owned_request(db,row.request_id,user.id)
    if row.status in {'completed','cancelled'} and body.status!=row.status:
        raise HTTPException(409,'Create a new assignment for a closed work order')
    row.status=body.status;row.notes=body.notes;row.scheduled_for=body.scheduled_for
    if body.status=='in_progress':req.status='in_progress'
    if body.status=='completed':req.status='resolved';req.resolved_at=m.utcnow()
    if req.conversation_id:
        db.add(m.MaintenanceMessage(conversation_id=req.conversation_id,role='bot',text=f'Your landlord updated the contractor work order: {body.status.replace("_"," ")}.'))
    db.commit()
    return work_order_out(db,row)
