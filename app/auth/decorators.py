"""
Small role-check decorators.

Recall has three roles: owner, staff (receptionist), and dentist. Most
day-to-day actions (viewing/confirming/cancelling appointments) are open to
any signed-in clinic user - that's the receptionist's whole job. A smaller
set of actions (clinic settings, WhatsApp credentials, managing the team,
adding/removing doctors) are owner-only, since misuse there can take down
the clinic's entire booking pipeline.
"""
from functools import wraps

from flask import abort
from flask_login import current_user


def owner_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_owner():
            abort(403)
        return view_func(*args, **kwargs)
    return wrapped
