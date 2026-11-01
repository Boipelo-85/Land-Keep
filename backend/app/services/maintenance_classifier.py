"""Local learned text classification, kept separate from emergency rules and chat generation."""
from functools import lru_cache
import logging
from pathlib import Path

from ..database import BASE_DIR

MODEL_PATH = BASE_DIR / 'ml/maintenance_classifier.joblib'
logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _load(path: str, modified: int):
    import joblib
    import sklearn
    bundle = joblib.load(path)  # Only the bundled, locally generated artifact is loaded.
    if bundle['metadata']['sklearn_version'] != sklearn.__version__:
        raise ValueError('Classifier library version changed; retrain with train_maintenance_classifier.py')
    return bundle


def load_model():
    try:
        return _load(str(MODEL_PATH), MODEL_PATH.stat().st_mtime_ns)
    except Exception:
        logger.warning('Trained maintenance classifier unavailable; run train_maintenance_classifier.py', exc_info=True)
        return None


def predict(text: str) -> dict | None:
    bundle = load_model()
    if bundle is None:
        return None
    pipeline, metadata = bundle['pipeline'], bundle['metadata']
    vector = pipeline.named_steps['text'].transform([text])
    scores = pipeline.named_steps['classifier'].predict_proba(vector)[0]
    best = int(scores.argmax())
    category = str(pipeline.named_steps['classifier'].classes_[best])
    score = float(scores[best])
    result = {'source': 'trained_local_model', 'category': category, 'score': round(score, 4),
            'needs_review': vector.nnz == 0 or score < metadata['review_score_threshold'],
            'model_version': metadata['model_version']}
    priority_model = bundle.get('priority_pipeline')
    if priority_model is not None:
        probabilities = priority_model.predict_proba([text])[0]
        index = int(probabilities.argmax())
        result['suggested_priority'] = str(priority_model.named_steps['classifier'].classes_[index])
        result['priority_score'] = round(float(probabilities[index]), 4)
    return result


def classify_request(request) -> None:
    result = predict(request.description)
    if result:
        request.predicted_category = result['category']
        request.classification_model_version = result['model_version']
        request.classification_score = result['score']
        request.predicted_urgency = result.get('suggested_priority')
        request.classification_priority_score = result.get('priority_score')


def request_classification(request) -> dict | None:
    if not request.classification_model_version:
        return None
    return {'source': 'trained_local_model', 'category': request.predicted_category,
            'score': request.classification_score,
            'needs_review': request.classification_score is None or request.classification_score < .55,
            'model_version': request.classification_model_version,
            'confirmed_category': request.confirmed_category,
            'suggested_priority': request.predicted_urgency, 'priority_score': request.classification_priority_score}


def status() -> dict:
    bundle = load_model()
    if bundle is None:
        return {'trained': False, 'message': 'Run backend/train_maintenance_classifier.py'}
    metadata = bundle['metadata']
    public = {key: metadata[key] for key in ['model_version', 'algorithm', 'trained_at', 'training_rows',
                'training_groups', 'training_source', 'sklearn_version', 'classes', 'limitations']}
    public['evaluation'] = {key: value for key, value in metadata['evaluation'].items() if key != 'errors'}
    return {'trained': True, **public}


def effective_priority(request) -> str:
    from .maintenance_chat import detect_emergency
    if request.ai_urgency == 'emergency' or detect_emergency(request.description):
        return 'emergency'
    if request.ai_urgency == 'high' or request.predicted_urgency == 'high':
        return 'high'
    return request.ai_urgency or request.predicted_urgency or 'medium'
