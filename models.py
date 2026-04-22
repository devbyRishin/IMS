from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # Admin, Reporter, Investigator
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)


class Incident(db.Model):
    __tablename__ = 'incidents'
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.String(20), unique=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), default='General')
    priority = db.Column(db.String(20), default='Medium')

    # Status flow: Pending Assignment → Assigned → In Progress → Resolved → Closed / Queued
    status = db.Column(db.String(50), default='Pending Assignment')

    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assigned_to_name = db.Column(db.String(100), nullable=True)

    # JSON list of user IDs who refused this incident
    refused_by = db.Column(db.Text, default="[]")

    findings = db.Column(db.Text)
    report_file = db.Column(db.String(255))

    # Admin close note
    close_note = db.Column(db.Text)
    closed_at = db.Column(db.DateTime, nullable=True)

    def get_refused_list(self):
        if self.refused_by is None:
            return []
        try:
            return json.loads(self.refused_by)
        except Exception:
            return []

    def add_refusal(self, user_id):
        current_list = self.get_refused_list()
        if user_id not in current_list:
            current_list.append(user_id)
            self.refused_by = json.dumps(current_list)