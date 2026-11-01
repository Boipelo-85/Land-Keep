from conftest import auth
from test_maintenance_chat import _tenant_with_lease


def test_contractor_assignment_is_scoped_and_visible_in_tenant_chat(client):
    _,lease_id=_tenant_with_lease()
    tenant=auth(client,'tenant-chat@test.com');landlord=auth(client,'landlord@test.com');other=auth(client,'other@test.com')
    payload={'name':'Local Plumbers','trade':'plumbing','phone':'+27821234567'}
    assert client.post('/contractors',json=payload,headers=tenant).status_code==403
    person=client.post('/contractors',json=payload,headers=landlord)
    assert person.status_code==201
    person=person.json()
    assert client.get('/contractors',headers=other).json()==[]
    cid=client.post('/maintenance/conversations',json={'lease_id':lease_id},headers=tenant).json()['id']
    rid=client.post(f'/maintenance/conversations/{cid}/escalate',headers=tenant).json()['request_id']
    url=f'/contractors/requests/{rid}/assign'
    body={'contractor_id':person['id'],'scheduled_for':'2026-11-03','notes':'Inspect kitchen tap'}
    assert client.post(url,json=body,headers=other).status_code==404
    assigned=client.post(url,json=body,headers=landlord)
    assert assigned.status_code==201
    order=assigned.json();assert order['status']=='scheduled'
    transcript=client.get(f'/maintenance/conversations/{cid}',headers=tenant).json()['messages']
    assert 'Local Plumbers' in transcript[-1]['text']
    update=f"/contractors/work-orders/{order['id']}"
    assert client.patch(update,json={'status':'completed'},headers=other).status_code==404
    assert client.patch(update,json={'status':'completed'},headers=landlord).status_code==200
    request=client.get('/maintenance/requests',headers=landlord).json()[0]
    assert request['status']=='resolved'
