# Trained maintenance classifier

This archive includes an actual fitted scikit-learn model at `backend/ml/maintenance_classifier.joblib`. It runs locally without an Anthropic key. It classifies requests into **plumbing, electrical, security, and general repairs**. It also includes a second fitted classifier for advisory low/high priority. It is not the conversational language model: Claude or the local guidance service still handles replies, and emergency rules still determine safety escalation.

## How it was trained

- Algorithm: word/bigram and character TF-IDF features with logistic regression. Coefficients are fitted from labelled text, not hand-written keyword classification rules.
- Training set: 400 synthetic reports from the existing LandKeep demo generator, with 51 normalized issue-template groups.
- Labels/counts: {'electrical': 86, 'general': 126, 'plumbing': 133, 'security': 55}.
- Model version: `tfidf-logreg-v2-d64123b82e55`.
- Library version: scikit-learn `1.9.1` (pinned in requirements).
- Input: request description text. Photos are not inputs to this classifier.

## Evaluation

The evaluation fit used 299 rows and held out 101 rows. Whole normalized issue-template groups were kept on one side of the split, with zero shared groups. Vectorizers were fitted only on evaluation training rows. The bundled final model was subsequently fitted on all 400 labelled rows.

- Group-held-out accuracy: **70.3%**.
- Group-held-out macro F1: **0.677**.
- Separate assistant-authored synthetic QA set: **95.8%** on 24 examples. These examples were not included in fitting and were not used to tune the model. This is a tiny check set, not a production benchmark.

| Category | Precision | Recall | F1 | Test rows |
|---|---:|---:|---:|---:|
| electrical | 0.625 | 0.714 | 0.667 | 21 |
| general | 0.621 | 0.545 | 0.581 | 33 |
| plumbing | 0.938 | 0.882 | 0.909 | 34 |
| security | 0.500 | 0.615 | 0.552 | 13 |

Full metrics, confusion matrices and errors are in `backend/ml/maintenance_classifier.json`. These are **synthetic-data results**, not evidence of real-world accuracy. Real tenant reports, verified labels, more varied language, a larger independent test set, and error review are needed before production use. Model scores shown in the app are not calibrated probabilities of correctness. Scores below 0.55 request human review; this is a conservative interface threshold, not a calibrated confidence guarantee.

## Runtime behavior

New manual reports and reports created from chat automatically run the trained classifier. The predicted category, model version, and model score are stored separately from landlord-confirmed labels. Landlords see the suggestion and can confirm or correct it without overwriting the original prediction. A classifier outage does not block maintenance reporting. Existing historical requests are not automatically relabelled.

Emergency detection, urgency and safe interim advice are kept separate. A wrong learned category cannot downgrade a gas/electrical/fire emergency. The model does not predict late payments, detect recurring issues, diagnose faults, generate free-form chat replies, or assess photos.

## Run and retrain

Start the project with `START-LANDKEEP.cmd`. It installs the pinned model dependency and checks the bundled model; if absent or incompatible, it retrains from the bundled labelled CSV without reading/resetting your database.

From the Land-Keep root, retrain on the bundled synthetic data:

```powershell
./.landkeep-runtime/Scripts/python.exe backend/train_maintenance_classifier.py
```

For a reviewed CSV with `text,category` columns and at least four distinct issue groups per class:

```powershell
./.landkeep-runtime/Scripts/python.exe backend/train_maintenance_classifier.py --data reviewed_requests.csv --source "Reviewed maintenance reports"
```

Restart the backend after retraining. Use only locally generated trusted model artifacts, not joblib/pickle files from uploads. Landlord corrections are recorded for future review; there is no silent online learning or automatic cross-agency data export.

To inspect status while signed in, call `GET /maintenance/classifier/status`. The landlord screen shows model scores and its category confirmation control. The existing chat guidance and Apply fixes are retained.


## Trained priority and chat routing update

The bundled v2 artifact also fits a separate TF-IDF/logistic-regression classifier to the dataset's low/high urgency labels. It records suggested priority and model score alongside category, while emergency detection overrides any low learned suggestion. The local chat can use the learned category to choose a safe clarifying question when a phrase is unfamiliar; it is still not a generative language model.

Priority group-held-out accuracy: 72.3%; macro F1: 0.606. These are synthetic-data results, not production performance guarantees. No priority labels were available for the small separate category QA set.

## Fast tenant complaint replies

A separate fitted local intent model now uses 180 assistant-authored synthetic
complaints, 15 per intent: leaks, no water, blocked drains, electrical supply,
lighting, hot water, keys/access, damp/mould, pests, noise, rent/payment questions,
and unanswered maintenance/contractor follow-ups. Training does not read the
application database or fine-tune Gemini. Run `backend/train_tenant_complaints.py`
with the project Python environment to rebuild it.

The model uses word/character TF-IDF and logistic regression. High-scoring,
well-separated predictions with matching vocabulary select reviewed reply
text immediately, before Gemini. This is trained intent classification plus
response templates, not a locally trained conversational language model.
Short/uncertain messages and photos continue through the existing AI flow.
Emergency detection and explicit landlord-report actions take precedence.

The 75/25 stratified synthetic phrase holdout had 45 test examples: accuracy
57.8%, macro F1 0.555. Related phrasing may occur on both sides, so this is not
an independent real-world benchmark. The fixed confidence/margin/similarity
checks routed 14/45 examples locally (31.1% coverage); all 14 were correct on
this small test. Do not interpret that as guaranteed accuracy. Warm classification
averaged about 4 ms in the recorded run; full request time also includes server,
database, and first-load costs. No real tenant reports were used.

Artifacts: `backend/ml/tenant_complaints.joblib` and its JSON metrics.
Training examples: `backend/ml/training/tenant_complaints.json`.
Set `LANDKEEP_LOCAL_COMPLAINTS=false` to disable local routing.
