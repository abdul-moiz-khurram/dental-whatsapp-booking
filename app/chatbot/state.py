import json

from app.extensions import db
from app.models import ConversationState


def get_state(clinic_id: int, phone: str) -> ConversationState:
    state = ConversationState.query.filter_by(clinic_id=clinic_id, patient_phone=phone).first()
    if not state:
        state = ConversationState(clinic_id=clinic_id, patient_phone=phone, step="menu", data="{}")
        db.session.add(state)
        db.session.commit()
    return state


def save_state(state: ConversationState, step: str, data: dict):
    state.step = step
    state.data = json.dumps(data)
    db.session.commit()


def reset_state(state: ConversationState):
    save_state(state, "menu", {})


def get_data(state: ConversationState) -> dict:
    try:
        return json.loads(state.data or "{}")
    except (TypeError, ValueError):
        return {}
