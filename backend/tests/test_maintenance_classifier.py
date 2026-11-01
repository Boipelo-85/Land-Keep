import hashlib
import json
from pathlib import Path

from app import models as m
from app.database import BASE_DIR, SessionLocal
from app.services import maintenance_classifier as classifier
from conftest import auth
from test_maintenance_chat import _tenant_with_lease


def test_bundled_model_is_trained_and_evaluation_has_no_template_overlap():
    bundle = classifier.load_model()
    assert bundle is not None
    assert hasattr(bundle['pipeline'].named_steps['classifier'], 'coef_')
    metadata = bundle['metadata']
    assert metadata['training_rows'] == 400
    assert set(metadata['classes']) == set(m.CATEGORIES)
    assert metadata['evaluation']['template_overlap'] == 0
    assert metadata['evaluation']['train_rows'] + metadata['evaluation']['test_rows'] == 400
    data = BASE_DIR / 'ml/training/maintenance_synthetic.csv'
    assert hashlib.sha256(data.read_bytes()).hexdigest() == metadata['data_sha256']
    assert metadata['independent_synthetic_evaluation']['rows'] == 24


def test_model_predicts_four_categories_and_flags_empty_input():
    for text, expected in [
        ('The kitchen tap is leaking', 'plumbing'),
        ('The electrical socket has stopped working', 'electrical'),
        ('I lost my keys and cannot open the door lock', 'security'),
        ('The paint is peeling off the bedroom wall', 'general'),
    ]:
        result = classifier.predict(text)
        assert result['source'] == 'trained_local_model'
        assert result['category'] == expected
        assert 0 <= result['score'] <= 1
        assert result['model_version'].startswith('tfidf-logreg-')
    assert classifier.predict('')['needs_review'] is True


def test_classifier_missing_does_not_break_reporting(client, monkeypatch):
    _, _ = _tenant_with_lease()
    monkeypatch.setattr(classifier, 'MODEL_PATH', Path('/does-not-exist/model.joblib'))
    headers = auth(client, 'tenant-chat@test.com')
    response = client.post('/maintenance', data={'description': 'My kitchen tap is leaking'}, headers=headers)
    assert response.status_code == 201
    assert response.json()['classification'] is None
    assert client.get('/maintenance/classifier/status', headers=headers).json()['trained'] is False


def test_report_records_real_prediction_and_landlord_correction(client):
    _, _ = _tenant_with_lease()
    tenant = auth(client, 'tenant-chat@test.com')
    landlord = auth(client, 'landlord@test.com')
    response = client.post('/maintenance', data={'description': 'My kitchen tap is leaking'}, headers=tenant)
    assert response.status_code == 201
    saved = response.json()
    assert saved['classification']['category'] == 'plumbing'
    rid = saved['id']
    other = auth(client, 'other@test.com')
    assert client.patch(f'/maintenance/requests/{rid}/classification', json={'category': 'general'}, headers=other).status_code == 404
    assert client.patch(f'/maintenance/requests/{rid}/classification', json={'category': 'general'}, headers=tenant).status_code == 403
    corrected = client.patch(f'/maintenance/requests/{rid}/classification', json={'category': 'general'}, headers=landlord)
    assert corrected.status_code == 200
    assert corrected.json()['classification']['category'] == 'plumbing'
    assert corrected.json()['confirmed_category'] == 'general'
    with SessionLocal() as db:
        req = db.get(m.MaintenanceRequest, rid)
        assert req.predicted_category == 'plumbing'
        assert req.confirmed_category == 'general'
        assert req.classification_score is not None
        assert req.classification_model_version
    status = client.get('/maintenance/classifier/status', headers=landlord)
    assert status.json()['trained'] is True


def test_prediction_cannot_downgrade_emergency_guidance(client, monkeypatch):
    _, lease_id = _tenant_with_lease()
    monkeypatch.setattr(classifier, 'predict', lambda text: {'category': 'general', 'score': .99, 'model_version': 'test-bad-prediction'})
    headers = auth(client, 'tenant-chat@test.com')
    cid = client.post('/maintenance/conversations', json={'lease_id': lease_id}, headers=headers).json()['id']
    response = client.post(f'/maintenance/conversations/{cid}/messages', data={'text': 'I smell gas'}, headers=headers)
    assert response.status_code == 200
    assert response.json()['status'] == 'escalated'
    assert response.json()['classification']['category'] == 'general'
    assert 'Leave the area' in response.json()['messages'][-1]['text']
    with SessionLocal() as db:
        req = db.get(m.MaintenanceRequest, response.json()['request_id'])
        assert req.ai_urgency == 'emergency'


def test_chat_escalation_records_prediction_and_keeps_interim_advice(client, monkeypatch):
    from app.services import maintenance_chat
    _, lease_id = _tenant_with_lease()
    headers = auth(client, 'tenant-chat@test.com')
    monkeypatch.setattr(maintenance_chat, 'analyze_with_claude', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
    cid = client.post('/maintenance/conversations', json={'lease_id': lease_id}, headers=headers).json()['id']
    client.post(f'/maintenance/conversations/{cid}/messages', data={'text': 'The kitchen tap is leaking'}, headers=headers)
    response = client.post(f'/maintenance/conversations/{cid}/escalate', headers=headers)
    assert response.json()['classification']['category'] == 'plumbing'
    assert 'catch drips' in response.json()['messages'][-1]['text']
    landlord = auth(client, 'landlord@test.com')
    reports = client.get('/maintenance/requests', headers=landlord).json()
    assert reports[0]['classification']['model_version']


def test_trained_priority_is_real_and_cannot_lower_emergency():
    bundle=classifier.load_model()
    assert hasattr(bundle['priority_pipeline'].named_steps['classifier'],'coef_')
    result=classifier.predict('The kitchen pipe is leaking badly')
    assert result['suggested_priority'] in {'high','low'}
    assert 0 <= result['priority_score'] <= 1
    req=m.MaintenanceRequest(description='I smell gas in the kitchen',predicted_urgency='low',ai_urgency='medium')
    assert classifier.effective_priority(req)=='emergency'
