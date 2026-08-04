"""
Registers the reminder/recall background jobs with APScheduler.

Guarded so it only starts once per process - Flask's debug reloader spawns
a second process that would otherwise double every scheduled send.
"""
import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.chatbot.automation import send_due_reminders, send_due_recalls

_scheduler = None


def init_scheduler(app):
    global _scheduler

    if not app.config.get("SCHEDULER_ENABLED", True):
        return

    # Under `flask run --debug` / the Werkzeug reloader, the reloader parent
    # process doesn't set WERKZEUG_RUN_MAIN - only the actual worker does.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        func=lambda: send_due_reminders(app),
        trigger="interval",
        minutes=30,
        id="send_due_reminders",
        replace_existing=True,
    )
    _scheduler.add_job(
        func=lambda: send_due_recalls(app),
        trigger="interval",
        hours=24,
        id="send_due_recalls",
        replace_existing=True,
    )
    _scheduler.start()
    app.logger.info("Reminder/recall scheduler started.")
