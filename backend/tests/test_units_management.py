from datetime import date
from conftest import auth
from app import models as m
from app.database import SessionLocal


def test_landlord_publish_tenant_browse_and_apply(client):
    landlord = auth(client, 'landlord@test.com')
    other = auth(client, 'other@test.com')
    response = client.post('/units/properties', json={'name':'Karabo Court','address':'25 Main Road','city':'Pretoria'}, headers=landlord)
    assert response.status_code == 201
    prop = response.json()
    assert prop['id'] not in [p['id'] for p in client.get('/units/properties', headers=other).json()]
    payload = {'property_id':prop['id'], 'unit_number':'B01','bedrooms':2,'monthly_rent':6500}
    assert client.post('/units', json=payload, headers=other).status_code == 404
    response = client.post('/units', json=payload, headers=landlord)
    assert response.status_code == 201
    unit = response.json()
    assert unit['listed_for_applications'] is True
    assert unit['id'] in [u['id'] for u in client.get('/units/mine',headers=landlord).json()]
    assert unit['id'] not in [u['id'] for u in client.get('/units/mine',headers=other).json()]
    assert unit['id'] in [u['id'] for u in client.get('/units/vacant').json()]
    assert client.post('/units', json={**payload,'unit_number':' b01 '}, headers=landlord).status_code == 409
    registration = client.post('/auth/register',json={'full_name':'New Applicant','email':'new-unit@test.com','password':'password123'})
    tenant = {'Authorization': 'Bearer ' + registration.json()['token']}
    assert client.get('/units/mine',headers=tenant).status_code == 403
    assert client.post('/units',json=payload,headers=tenant).status_code == 403
    assert client.post('/units/properties',json={'name':'Fake','address':'1 Fake Road','city':'Pretoria'},headers=tenant).status_code == 403
    response = client.post('/applications',json={'unit_id':unit['id'],'monthly_income':22000,'id_number':'9001015009087','consent_given':True},headers=tenant)
    assert response.status_code == 201
    assert response.json()['unit']['id'] == unit['id']


def test_unit_validation_and_lease_visibility(client):
    landlord = auth(client, 'landlord@test.com')
    prop = client.get('/units/properties', headers=landlord).json()[0]
    payload = {'property_id':prop['id'],'unit_number':'Studio','bedrooms':0,'monthly_rent':3500.50}
    for change in [{'monthly_rent':0},{'monthly_rent':-5},{'bedrooms':-1},{'bedrooms':2.5},{'unit_number':'  '}]:
        assert client.post('/units', json={**payload,**change}, headers=landlord).status_code == 422
    assert client.post('/units', json=payload).status_code == 401
    unit = client.post('/units', json=payload, headers=landlord).json()
    with SessionLocal() as db:
        user = db.query(m.User).filter_by(email='landlord@test.com').one()
        lease = m.Lease(unit_id=unit['id'],tenant_id=user.id,start_date=date(2026,1,1),end_date=date(2027,1,1),monthly_rent=3500.5,deposit=3500.5,due_day=1,status='pending')
        db.add(lease);db.commit()
    assert unit['id'] not in [u['id'] for u in client.get('/units/vacant').json()]
    mine = client.get('/units/mine', headers=landlord).json()
    assert next(u for u in mine if u['id']==unit['id'])['listed_for_applications'] is False
