import os
from flask import Flask, render_template

from app.config import Config
from app.extensions import db, login_manager, migrate, csrf, mail, limiter


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.chatbot.routes import chatbot_bp
    from app.appointments.routes import appointments_bp
    from app.doctors.routes import doctors_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(chatbot_bp, url_prefix="/webhook")
    app.register_blueprint(appointments_bp, url_prefix="/dashboard/appointments")
    app.register_blueprint(doctors_bp, url_prefix="/dashboard/doctors")

    # The WhatsApp webhook is called by Twilio/Meta's servers, not a browser
    # with our session cookie - it can never carry a CSRF token, and doesn't
    # need one since it's not a browser-driven state change on behalf of a
    # logged-in user.
    csrf.exempt(chatbot_bp)

    from app.scheduler import init_scheduler
    init_scheduler(app)

    @app.route("/")
    def landing():
        return render_template("landing/index.html")

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("dashboard/403.html"), 403

    @app.cli.command("init-db")
    def init_db():
        """Create all tables. Run with: flask init-db"""
        db.create_all()
        print("Database tables created.")

    return app
