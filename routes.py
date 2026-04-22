import os, json
from flask import render_template, request, redirect, url_for, session, current_app, flash
from werkzeug.utils import secure_filename
from models import db, User, Incident
from datetime import datetime


# ─────────────────────────────────────────────
# Helper: pick the least-busy investigator who
# hasn't refused this incident yet.
# ─────────────────────────────────────────────
def find_next_investigator(incident):
    refused_ids = incident.get_refused_list()
    available = User.query.filter(
        User.role == 'Investigator',
        ~User.id.in_(refused_ids)
    ).all()

    if not available:
        return None

    best = min(
        available,
        key=lambda u: Incident.query.filter_by(assigned_to_id=u.id)
                        .filter(Incident.status.in_(['Assigned', 'In Progress']))
                        .count()
    )
    return best


def configure_routes(app):

    # ── Auth ──────────────────────────────────
    @app.route('/')
    def home():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        return render_template('login.html')

    @app.route('/login', methods=['POST'])
    def login():
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and user.check_password(request.form.get('password')):
            session.update({
                'user_id':   user.id,
                'user_name': user.fullname,
                'user_role': user.role
            })
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
        return redirect(url_for('home'))

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            if User.query.filter_by(email=request.form.get('email')).first():
                flash('Email already registered.', 'warning')
                return redirect(url_for('register'))
            u = User(
                fullname=request.form.get('fullname'),
                email=request.form.get('email'),
                role=request.form.get('role')
            )
            u.set_password(request.form.get('password'))
            db.session.add(u)
            db.session.commit()
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('home'))
        return render_template('register.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('home'))

    # ── Dashboard ─────────────────────────────
    @app.route('/dashboard')
    def dashboard():
        if 'user_id' not in session:
            return redirect('/')

        uid  = session['user_id']
        role = session['user_role']

        if role == 'Investigator':
            # Active: assigned/in-progress to this investigator
            active = Incident.query.filter_by(assigned_to_id=uid).filter(
                Incident.status.in_(['Assigned', 'In Progress'])
            ).order_by(Incident.created_at.desc()).all()

            # History: resolved or closed by this investigator
            history = Incident.query.filter_by(assigned_to_id=uid).filter(
                Incident.status.in_(['Resolved', 'Closed'])
            ).order_by(Incident.created_at.desc()).all()

            # Queued – no one assigned yet (investigator can self-pick)
            queued = Incident.query.filter_by(
                status='Queued', assigned_to_id=None
            ).order_by(Incident.created_at.asc()).all()

            return render_template('dashboard.html',
                                   incidents=active,
                                   history=history,
                                   queued=queued)

        # Admin / Reporter see everything
        all_inc = Incident.query.order_by(Incident.created_at.desc()).all()

        # For admin: investigator performance stats
        investigators = []
        if role == 'Admin':
            invs = User.query.filter_by(role='Investigator').all()
            for inv in invs:
                investigators.append({
                    'name':     inv.fullname,
                    'email':    inv.email,
                    'active':   Incident.query.filter_by(assigned_to_id=inv.id)
                                    .filter(Incident.status.in_(['Assigned', 'In Progress'])).count(),
                    'resolved': Incident.query.filter_by(assigned_to_id=inv.id)
                                    .filter(Incident.status.in_(['Resolved', 'Closed'])).count(),
                })

        return render_template('dashboard.html',
                               incidents=all_inc,
                               investigators=investigators)

    # ── Reporter: log new incident ─────────────
    @app.route('/report', methods=['POST'])
    def report():
        if 'user_id' not in session:
            return redirect('/')

        count  = Incident.query.count()
        new_id = f"INC-{count + 1:04d}"

        inc = Incident(
            incident_id  = new_id,
            title        = request.form.get('title'),
            description  = request.form.get('description'),
            category     = request.form.get('category', 'General'),
            priority     = request.form.get('priority', 'Medium'),
            created_by   = session.get('user_name'),
            status       = 'Pending Assignment',
            refused_by   = '[]'
        )

        target = find_next_investigator(inc)
        if target:
            inc.assigned_to_id   = target.id
            inc.assigned_to_name = target.fullname
            inc.status           = 'Assigned'
        else:
            inc.status = 'Queued'

        db.session.add(inc)
        db.session.commit()
        flash(f'Incident {new_id} logged successfully.', 'success')
        return redirect(url_for('dashboard'))

    # ── Investigator: accept ───────────────────
    @app.route('/action/<int:id>/accept')
    def accept_incident(id):
        if 'user_id' not in session:
            return redirect('/')
        inc = Incident.query.get_or_404(id)
        inc.status = 'In Progress'
        db.session.commit()
        flash(f'You accepted {inc.incident_id}.', 'success')
        return redirect(url_for('dashboard'))

    # ── Investigator: refuse ───────────────────
    @app.route('/action/<int:id>/refuse')
    def refuse_incident(id):
        if 'user_id' not in session:
            return redirect('/')
        inc = Incident.query.get_or_404(id)

        inc.add_refusal(session['user_id'])

        next_inv = find_next_investigator(inc)
        if next_inv:
            inc.assigned_to_id   = next_inv.id
            inc.assigned_to_name = next_inv.fullname
            inc.status           = 'Assigned'
            flash(f'Incident {inc.incident_id} re-assigned to {next_inv.fullname}.', 'info')
        else:
            inc.assigned_to_id   = None
            inc.assigned_to_name = None
            inc.status           = 'Queued'
            flash(f'Incident {inc.incident_id} moved to queue — no investigators available.', 'warning')

        db.session.commit()
        return redirect(url_for('dashboard'))

    # ── Investigator: self-pick from queue ─────
    @app.route('/action/<int:id>/pickup')
    def pickup_incident(id):
        if 'user_id' not in session or session['user_role'] != 'Investigator':
            return redirect('/')
        inc = Incident.query.get_or_404(id)
        if inc.status != 'Queued':
            flash('This incident is no longer in queue.', 'warning')
            return redirect(url_for('dashboard'))

        inc.assigned_to_id   = session['user_id']
        inc.assigned_to_name = session['user_name']
        inc.status           = 'In Progress'
        db.session.commit()
        flash(f'You picked up {inc.incident_id}.', 'success')
        return redirect(url_for('dashboard'))

    # ── Investigator: submit resolution ────────
    @app.route('/solve/<int:id>', methods=['POST'])
    def solve(id):
        if 'user_id' not in session:
            return redirect('/')
        inc = Incident.query.get_or_404(id)
        inc.findings = request.form.get('findings_text')

        if 'evidence_pdf' in request.files:
            file = request.files['evidence_pdf']
            if file and file.filename:
                filename = secure_filename(f"REPORT_{inc.incident_id}.pdf")
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                inc.report_file = filename

        inc.status = 'Resolved'
        db.session.commit()
        flash(f'Incident {inc.incident_id} submitted for admin review.', 'success')
        return redirect(url_for('dashboard'))

    # ── Admin: verify & close ──────────────────
    @app.route('/close/<int:id>', methods=['POST'])
    def close_incident(id):
        if 'user_id' not in session or session['user_role'] != 'Admin':
            return redirect('/')
        inc = Incident.query.get_or_404(id)
        inc.status    = 'Closed'
        inc.close_note = request.form.get('close_note', '')
        inc.closed_at  = datetime.utcnow()
        db.session.commit()
        flash(f'Incident {inc.incident_id} has been closed.', 'success')
        return redirect(url_for('dashboard'))

    # ── File download ──────────────────────────
    @app.route('/download/<filename>')
    def download_file(filename):
        return current_app.send_static_file(f'uploads/{filename}')