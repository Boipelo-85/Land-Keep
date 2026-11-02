"""Train the local complaint router on synthetic text; does not access the database."""
from pathlib import Path
import hashlib
import json
import time
import joblib
import sklearn
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'ml/training/tenant_complaints.json'
OUTPUT = ROOT / 'ml/tenant_complaints.joblib'

def build():
    return Pipeline([('text', FeatureUnion([
        ('words', TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ('chars', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), sublinear_tf=True)),
    ], transformer_weights={'words': 1., 'chars': .5})),
    ('classifier', LogisticRegression(C=8, max_iter=2000, random_state=42))])

if __name__ == '__main__':
    rows = json.loads(DATA.read_text(encoding='utf-8'))
    texts = [r['text'] for r in rows]; labels = [r['intent'] for r in rows]
    train, test = train_test_split(np.arange(len(rows)), test_size=.25, stratify=labels, random_state=42)
    evaluated = build().fit([texts[i] for i in train], [labels[i] for i in train])
    expected = [labels[i] for i in test]; predicted = evaluated.predict([texts[i] for i in test])
    scores = evaluated.predict_proba([texts[i] for i in test]); sorted_scores = np.sort(scores, axis=1)
    vectors = evaluated.named_steps['text'].transform([texts[i] for i in train])
    from sklearn.metrics.pairwise import cosine_similarity
    similarities = cosine_similarity(evaluated.named_steps['text'].transform([texts[i] for i in test]), vectors).max(axis=1)
    routed = (sorted_scores[:, -1] >= .45) & ((sorted_scores[:, -1] - sorted_scores[:, -2]) >= .15) & (similarities >= .25)
    final = build().fit(texts, labels)
    started = time.perf_counter()
    for _ in range(20): final.predict_proba(['My kitchen sink will not drain'])
    metadata = {'version': 'tenant-intents-v1-' + hashlib.sha256(DATA.read_bytes()).hexdigest()[:12],
        'training_rows': len(rows), 'intent_count': len(set(labels)), 'sklearn_version': sklearn.__version__,
        'source': '180 assistant-authored synthetic tenant complaints; no private tenant data',
        'threshold': .45, 'margin': .15, 'minimum_similarity': .25,
        'evaluation': {'method': 'Stratified phrase holdout, 75% train and 25% test; related phrasings may occur on both sides',
            'test_rows': len(test), 'accuracy': float(accuracy_score(expected, predicted)),
            'macro_f1': float(f1_score(expected, predicted, average='macro')),
            'local_coverage': float(routed.mean()),
            'routed_accuracy': float(accuracy_score(np.array(expected)[routed], predicted[routed])) if routed.any() else None},
        'warm_classification_ms': (time.perf_counter()-started)/20*1000,
        'limitations': 'Text intent classification with reviewed response templates, not a generative model or photo analyser. Scores are uncalibrated. Synthetic evaluation is not real-world accuracy.'}
    joblib.dump({'pipeline': final, 'reference_vectors': final.named_steps['text'].transform(texts), 'metadata': metadata}, OUTPUT)
    OUTPUT.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata, indent=2))
