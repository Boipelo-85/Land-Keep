"""Fast trained complaint intents with conservative routing and reviewed reply text."""
from functools import lru_cache
from pathlib import Path
import logging

MODEL = Path(__file__).resolve().parents[2] / 'ml/tenant_complaints.joblib'
logger = logging.getLogger(__name__)
RESPONSES = {
    'leak': ('plumbing', "If safe, catch drips and move belongings away. Keep water away from plugs, and don't take pipes apart. Where is the leak, and is it a slow drip or a steady flow?"),
    'no_water': ('plumbing', "Check whether other taps have water and whether neighbours or the building manager know of a supply interruption. Don't adjust unfamiliar valves. Is it one tap or the whole unit, and are both hot and cold affected?"),
    'blocked_drain': ('plumbing', "Stop using the blocked fixture. Don't mix drain cleaners or dismantle pipes. Is it a sink, toilet, or shower, and is water backing up anywhere else?"),
    'power': ('electrical', "Don't open electrical panels, touch wiring, or repeatedly reset a tripping breaker. Check only an accessible prepaid meter display or outage notice, if safe. Is the whole unit affected, and do neighbouring units have power? Your landlord can arrange an electrician."),
    'lighting': ('electrical', "Avoid touching a loose or damaged fitting, opening light fittings, or working on wiring. Your landlord can arrange a qualified electrician. Is this one light or several, and have you noticed heat or a burning smell?"),
    'hot_water': ('appliance', "Check whether cold water still runs and whether there is an announced water or electricity interruption. Don't open the geyser or touch its wiring or reset controls. Is all hot water affected, and is there any visible leaking?"),
    'keys': ('doors_locks', "Are you locked out or safely inside? Don't force the door or lock. Contact the landlord or building manager for authorised access or a replacement key. Could the missing keys be linked to your address?"),
    'damp': ('roof_damp', "Move belongings away and ventilate if safe. Don't climb, touch a sagging ceiling, scrape mould, or mix cleaning chemicals. Which wall or ceiling is affected, and does it get worse after rain?"),
    'pests': ('pests', "Keep food sealed and note where pests or droppings appear. Avoid handling rodents or using unfamiliar chemicals. Your landlord can arrange pest control. What pest have you seen, and in which room?"),
    'noise': ('other', "Note the dates, times, location, and duration of the disturbance. Avoid confronting anyone if you feel unsafe, and raise it with your landlord or building manager. Is the noise happening now or repeatedly at certain times?"),
    'rent': ('other', "Open Pay rent to check recorded charges and payment history, and My lease for the agreed rent and due date. Keep your payment reference and ask your landlord about discrepancies or payment arrangements. I can't confirm a payment from this chat. Is this about an incorrect charge, a missing payment, or difficulty paying?"),
    'followup': ('other', "Check the report and any contractor updates in Report a problem, and add when the issue started or worsened. I can't promise a repair time or confirm that the landlord has read it. Which report are you following up on, and has anything changed?"),
}

@lru_cache(maxsize=1)
def _load(modified):
    import joblib
    import sklearn
    bundle = joblib.load(MODEL)
    if bundle['metadata']['sklearn_version'] != sklearn.__version__:
        raise ValueError('Retrain tenant complaint model for this library version')
    return bundle

def predict_reply(text):
    # Short answers and references to earlier messages need conversational context.
    if len(text.split()) < 3:
        return None
    try:
        from sklearn.metrics.pairwise import cosine_similarity
        bundle = _load(MODEL.stat().st_mtime_ns)
        pipeline = bundle['pipeline']; metadata = bundle['metadata']
        vector = pipeline.named_steps['text'].transform([text])
        scores = pipeline.named_steps['classifier'].predict_proba(vector)[0]
        order = scores.argsort(); best = int(order[-1])
        similarity = float(cosine_similarity(vector, bundle['reference_vectors']).max())
        if scores[best] < metadata['threshold'] or scores[best]-scores[order[-2]] < metadata['margin'] or similarity < metadata['minimum_similarity']:
            return None
        intent = str(pipeline.named_steps['classifier'].classes_[best])
        category, reply = RESPONSES[intent]
        return {'intent': intent, 'category': category, 'reply': reply, 'score': float(scores[best]), 'version': metadata['version']}
    except Exception:
        logger.warning('Local complaint router unavailable', exc_info=True)
        return None
