import asyncio
import pytest
from app.services.tenant_complaints import predict_reply
from app.services import maintenance_chat as chat
from app.routers import maintenance
from test_maintenance_chat import _tenant_with_lease
from conftest import auth

@pytest.mark.parametrize('text,intent', [
    ('Water leaks underneath my sink','leak'),
    ('None of my taps have water','no_water'),
    ('The kitchen sink will not drain','blocked_drain'),
    ('My flat has no electricity','power'),
    ('The bedroom light does not turn on','lighting'),
    ('My geyser is not heating','hot_water'),
    ('I lost my apartment keys','keys'),
    ('There is mould on my bedroom wall','damp'),
    ('There are cockroaches in my kitchen','pests'),
    ('The neighbours play loud music at night','noise'),
    ('I paid but the balance has not updated','rent'),
    ('The contractor did not arrive','followup'),
])
def test_local_model_covers_all_complaint_intents(text, intent):
    result = predict_reply(text)
    assert result is not None
    assert result['intent'] == intent
    assert result['reply']

@pytest.mark.parametrize('text',['Yes','Only that one','What is quantum chromodynamics?','Check the picture hey'])
def test_unrelated_or_contextual_messages_are_not_guessed(text):
    assert predict_reply(text) is None


def test_clear_complaint_skips_network_and_saves_reply(client, monkeypatch):
    monkeypatch.setenv('LANDKEEP_LOCAL_COMPLAINTS','true')
    _, lease_id = _tenant_with_lease()
    headers = auth(client,'tenant-chat@test.com')
    cid = client.post('/maintenance/conversations',json={'lease_id':lease_id},headers=headers).json()['id']
    def no_network(*args,**kwargs):
        raise AssertionError('Clear local complaint must not wait for network')
    monkeypatch.setattr(chat,'analyze_with_ai',no_network)
    response = client.post(f'/maintenance/conversations/{cid}/messages',data={'text':'There are cockroaches in my kitchen'},headers=headers)
    assert response.status_code == 200
    assert response.json()['assistant_mode'] == 'trained_local'
    assert 'pest control' in response.json()['messages'][-1]['text']


def test_photos_bypass_local_text_router(monkeypatch):
    monkeypatch.setenv('LANDKEEP_LOCAL_COMPLAINTS','true')
    calls=[]
    def ai(text,paths,**kwargs):
        calls.append(paths)
        return chat.Analysis(reply='I can see the photo.',category='other',urgency='low',summary='Photo',likely_cause='Unknown',confidence=0,diy_appropriate=False)
    monkeypatch.setattr(chat,'analyze_with_ai',ai)
    result=asyncio.run(maintenance._analyze_with_deadline('tenant: There are cockroaches in my kitchen',['photo.png']))
    assert not result._from_local
    assert calls==[['photo.png']]
