```python
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from flask_socketio import SocketIO
import mysql.connector
from datetime import datetime
import os

app = Flask(__name__)

# Secret key is now read from environment variable
app.secret_key = os.environ.get('SECRET_KEY')

CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*")

# Maps user_id → socket SID for targeted notifications
user_sockets = {}

# Database configuration
# Values are read from environment variables
db_config = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD'),
    'database': os.environ.get('DB_NAME', 'job_scheduling'),
    'port': int(os.environ.get('DB_PORT', 3306))
}


def get_db():
    return mysql.connector.connect(**db_config)


# ── Auth Decorators ───────────────────────────────────────────────
def login_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)

    return decorated


def manager_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401

        if session.get('role') != 'manager':
            return jsonify({'error': 'Manager access required'}), 403

        return f(*args, **kwargs)

    return decorated


# ── Pages ─────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))

    return render_template('index.html')


@app.route('/login')
def login_page():
    return render_template('login.html')


# ── Auth API ──────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()

    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({
            'error': 'Email and password are required.'
        }), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM workers WHERE email=%s AND password=%s",
        (email, password)
    )

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if not user:
        return jsonify({
            'error': 'Invalid email or password.'
        }), 401

    session['user_id'] = user['id']
    session['user_name'] = user['name']
    session['role'] = user['role']
    session['avatar_color'] = user['avatar_color']

    return jsonify({
        'id': user['id'],
        'name': user['name'],
        'role': user['role'],
        'avatar_color': user['avatar_color']
    })


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()

    return jsonify({
        'message': 'Logged out'
    })


@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({
            'error': 'Not logged in'
        }), 401

    return jsonify({
        'id': session['user_id'],
        'name': session['user_name'],
        'role': session['role'],
        'avatar_color': session['avatar_color']
    })


# ── Helper: derive overall status from worker statuses ────────────
def derive_overall_status(worker_statuses):
    """
    ALL Pending/Scheduled → Scheduled
    ANY In Progress (and not all completed) → In Progress
    ALL Completed → Completed
    """

    if not worker_statuses:
        return 'Scheduled'

    s = set(worker_statuses)

    if s == {'Pending'}:
        return 'Scheduled'

    if s == {'Completed'}:
        return 'Completed'

    return 'In Progress'


def status_color(status):
    return {
        'Scheduled': '#2563eb',
        'In Progress': '#ea580c',
        'Completed': '#16a34a'
    }.get(status, '#2563eb')


def _conflict_msg(name, job_status, start_dt, end_dt):
    """
    Return a human-friendly 409 message that reflects
    the existing job's status.
    """

    s = start_dt.strftime('%I:%M %p')
    e = end_dt.strftime('%I:%M %p')
    d = start_dt.strftime('%d/%m/%Y')

    if job_status == 'Completed':
        return (
            f"{name} has already completed a task from {s} to {e} on {d}. "
            f"Please assign a different time or worker."
        )

    elif job_status == 'In Progress':
        return (
            f"{name} is currently assigned to a task from {s} to {e} on {d}. "
            f"Please assign a different time or worker."
        )

    else:
        return (
            f"{name} already has a scheduled task from {s} to {e} on {d}. "
            f"Please assign a different time or worker."
        )


# ── GET /api/jobs ─────────────────────────────────────────────────
@app.route('/api/jobs', methods=['GET'])
@login_required
def get_jobs():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if session['role'] == 'worker':

        cursor.execute("""
            SELECT j.id,
                   c.name AS customer,
                   l.name AS location,
                   j.start_time,
                   j.end_time,
                   j.created_by
            FROM jobs j
            JOIN customers c ON j.customer_id = c.id
            LEFT JOIN locations l ON j.location_id = l.id
            JOIN job_workers jw ON j.id = jw.job_id
            WHERE jw.worker_id = %s
            ORDER BY j.start_time
        """, (session['user_id'],))

    else:

        cursor.execute("""
            SELECT j.id,
                   c.name AS customer,
                   l.name AS location,
                   j.start_time,
                   j.end_time,
                   j.created_by
            FROM jobs j
            JOIN customers c ON j.customer_id = c.id
            LEFT JOIN locations l ON j.location_id = l.id
            ORDER BY j.start_time
        """)

    jobs = cursor.fetchall()

    # All workers + their individual statuses
    cursor.execute("""
        SELECT jw.job_id,
               w.id AS worker_id,
               w.name AS worker_name,
               w.avatar_color,
               jw.status AS worker_status
        FROM job_workers jw
        JOIN workers w ON jw.worker_id = w.id
    """)

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    workers_by_job = {}

    for r in rows:
        workers_by_job.setdefault(r['job_id'], []).append({
            'id': r['worker_id'],
            'name': r['worker_name'],
            'avatar_color': r['avatar_color'],
            'worker_status': r['worker_status']
        })

    result = []

    for job in jobs:

        wlist = workers_by_job.get(job['id'], [])

        statuses = [
            w['worker_status']
            for w in wlist
        ]

        overall = derive_overall_status(statuses)

        completed_count = sum(
            1 for s in statuses
            if s == 'Completed'
        )

        total_count = len(statuses)

        pct = (
            int(completed_count / total_count * 100)
            if total_count
            else 0
        )

        result.append({
            'id': job['id'],
            'title': f"{', '.join(w['name'] for w in wlist)} — {job['customer']}",
            'start': job['start_time'].strftime('%Y-%m-%dT%H:%M:%S'),
            'end': job['end_time'].strftime('%Y-%m-%dT%H:%M:%S'),
            'status': overall,
            'customer': job['customer'],
            'location': job['location'] or '-',
            'workers': wlist,
            'worker_names': ', '.join(
                w['name'] for w in wlist
            ),
            'completed_count': completed_count,
            'total_count': total_count,
            'progress_pct': pct,
            'backgroundColor': status_color(overall),
            'borderColor': status_color(overall),
        })

    return jsonify(result)


# ── GET /api/jobs/<id> ────────────────────────────────────────────
@app.route('/api/jobs/<int:job_id>')
@login_required
def get_job(job_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT j.*,
               c.name AS customer,
               l.name AS location
        FROM jobs j
        JOIN customers c ON j.customer_id = c.id
        LEFT JOIN locations l ON j.location_id = l.id
        WHERE j.id = %s
    """, (job_id,))

    job = cursor.fetchone()

    if not job:
        cursor.close()
        conn.close()

        return jsonify({
            'error': 'Job not found'
        }), 404

    cursor.execute("""
        SELECT w.id,
               w.name,
               w.avatar_color,
               jw.status AS worker_status
        FROM job_workers jw
        JOIN workers w ON jw.worker_id = w.id
        WHERE jw.job_id = %s
    """, (job_id,))

    job['workers'] = cursor.fetchall()

    statuses = [
        w['worker_status']
        for w in job['workers']
    ]

    job['status'] = derive_overall_status(statuses)

    job['completed_count'] = sum(
        1 for s in statuses
        if s == 'Completed'
    )

    job['total_count'] = len(statuses)

    job['progress_pct'] = (
        int(
            job['completed_count'] /
            job['total_count'] *
            100
        )
        if job['total_count']
        else 0
    )

    cursor.execute("""
        SELECT jl.action,
               jl.created_at,
               w.name AS done_by_name
        FROM job_logs jl
        LEFT JOIN workers w ON jl.done_by = w.id
        WHERE jl.job_id = %s
        ORDER BY jl.created_at ASC
    """, (job_id,))

    job['logs'] = [
        {
            **l,
            'created_at': l['created_at'].strftime(
                '%d %b %Y %I:%M %p'
            )
        }
        for l in cursor.fetchall()
    ]

    job['start_time'] = job['start_time'].strftime(
        '%Y-%m-%dT%H:%M:%S'
    )

    job['end_time'] = job['end_time'].strftime(
        '%Y-%m-%dT%H:%M:%S'
    )

    job.pop('created_by', None)

    cursor.close()
    conn.close()

    return jsonify(job)


# ── GET /api/workers, /api/customers, /api/locations ─────────────
@app.route('/api/workers')
@login_required
def get_workers():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT id, name, avatar_color "
        "FROM workers WHERE role='worker'"
    )

    data = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(data)


@app.route('/api/customers')
@login_required
def get_customers():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM customers")

    data = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(data)


@app.route('/api/locations')
@login_required
def get_locations():

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM locations")

    data = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(data)


# ── POST /api/jobs  (create) ──────────────────────────────────────
@app.route('/api/jobs', methods=['POST'])
@manager_required
def create_job():

    data = request.get_json()

    errors = {}

    if not data.get('customer_id'):
        errors['customer_id'] = 'Customer is required.'

    if not data.get('worker_ids'):
        errors['worker_ids'] = 'At least one worker is required.'

    if not data.get('start_time'):
        errors['start_time'] = 'Start time is required.'

    if not data.get('end_time'):
        errors['end_time'] = 'End time is required.'

    if errors:
        return jsonify({
            'errors': errors
        }), 400

    start_time = datetime.fromisoformat(
        data['start_time']
    )

    end_time = datetime.fromisoformat(
        data['end_time']
    )

    if end_time <= start_time:
        return jsonify({
            'errors': {
                'end_time':
                'End time must be after start time.'
            }
        }), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Overlap check per worker
    # ALL statuses:
    # Scheduled, In Progress, Completed
    for wid in data['worker_ids']:

        cursor.execute("""
            SELECT j.start_time,
                   j.end_time,
                   j.status AS job_status,
                   w.name AS worker_name
            FROM jobs j
            JOIN job_workers jw ON j.id = jw.job_id
            JOIN workers w ON jw.worker_id = w.id
            WHERE jw.worker_id = %s
              AND j.start_time < %s
              AND j.end_time > %s
        """, (
            wid,
            end_time,
            start_time
        ))

        conflict = cursor.fetchone()

        if conflict:

            cursor.close()
            conn.close()

            msg = _conflict_msg(
                conflict['worker_name'],
                conflict['job_status'],
                conflict['start_time'],
                conflict['end_time']
            )

            return jsonify({
                'error': msg
            }), 409

    if data.get('_check_only'):

        cursor.close()
        conn.close()

        return jsonify({
            'message': 'No conflict'
        }), 200

    cursor.execute("""
        INSERT INTO jobs
        (
            customer_id,
            location_id,
            start_time,
            end_time,
            status,
            created_by
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            'Scheduled',
            %s
        )
    """, (
        data['customer_id'],
        data.get('location_id'),
        start_time,
        end_time,
        session['user_id']
    ))

    job_id = cursor.lastrowid

    for wid in data['worker_ids']:

        cursor.execute(
            """
            INSERT INTO job_workers
            (
                job_id,
                worker_id,
                status
            )
            VALUES
            (
                %s,
                %s,
                'Pending'
            )
            """,
            (job_id, wid)
        )

    cursor.execute(
        """
        INSERT INTO job_logs
        (
            job_id,
            action,
            done_by
        )
        VALUES
        (
            %s,
            %s,
            %s
        )
        """,
        (
            job_id,
            f"Job created by {session['user_name']}",
            session['user_id']
        )
    )

    # Fetch customer details
    cursor.execute(
        "SELECT name FROM customers WHERE id=%s",
        (data['customer_id'],)
    )

    customer_row = cursor.fetchone()

    customer_name = (
        customer_row['name']
        if customer_row
        else 'Unknown'
    )

    # Fetch location details
    location_name = '-'

    if data.get('location_id'):

        cursor.execute(
            "SELECT name FROM locations WHERE id=%s",
            (data['location_id'],)
        )

        loc_row = cursor.fetchone()

        location_name = (
            loc_row['name']
            if loc_row
            else '-'
        )

    conn.commit()

    cursor.close()
    conn.close()

    # Broadcast global refresh
    socketio.emit(
        'jobs_updated',
        {'message': 'New job created'}
    )

    # Send targeted notification
    notification_payload = {
        'job_id': job_id,
        'customer': customer_name,
        'location': location_name,
        'start': start_time.strftime(
            '%d %b %Y %I:%M %p'
        ),
        'end': end_time.strftime(
            '%I:%M %p'
        ),
        'manager': session['user_name'],
    }

    for wid in data['worker_ids']:

        sid = user_sockets.get(wid)

        if sid:

            socketio.emit(
                'task_assigned',
                notification_payload,
                to=sid
            )

    return jsonify({
        'message': 'Job created successfully'
    }), 201


# ── PUT /api/jobs/<id>/workers/<worker_id>/status ─────────────────
@app.route(
    '/api/jobs/<int:job_id>/workers/<int:worker_id>/status',
    methods=['PUT']
)
@login_required
def update_worker_status(job_id, worker_id):

    data = request.get_json()

    new_status = data.get('worker_status')

    if new_status not in (
        'In Progress',
        'Completed'
    ):
        return jsonify({
            'error':
            'Invalid status. Use "In Progress" or "Completed"'
        }), 400

    # Workers can only update their own status
    if (
        session['role'] == 'worker'
        and session['user_id'] != worker_id
    ):
        return jsonify({
            'error':
            'You can only update your own status'
        }), 403

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Confirm worker is assigned
    cursor.execute(
        """
        SELECT status
        FROM job_workers
        WHERE job_id=%s
          AND worker_id=%s
        """,
        (job_id, worker_id)
    )

    row = cursor.fetchone()

    if not row:

        cursor.close()
        conn.close()

        return jsonify({
            'error':
            'Worker not assigned to this job'
        }), 404

    # Prevent going backwards
    current = row['status']

    order = {
        'Pending': 0,
        'Started': 1,
        'In Progress': 1,
        'Completed': 2
    }

    if (
        order.get(new_status, 0)
        <= order.get(current, 0)
        and current != 'Pending'
    ):

        cursor.close()
        conn.close()

        return jsonify({
            'error':
            f'Cannot change status from {current} to {new_status}'
        }), 400

    # Map UI value to DB ENUM
    db_status = (
        'Started'
        if new_status == 'In Progress'
        else 'Completed'
    )

    cursor.execute(
        """
        UPDATE job_workers
        SET status=%s
        WHERE job_id=%s
          AND worker_id=%s
        """,
        (
            db_status,
            job_id,
            worker_id
        )
    )

    # Log action
    action_label = (
        'started'
        if db_status == 'Started'
        else 'completed'
    )

    cursor.execute(
        """
        INSERT INTO job_logs
        (
            job_id,
            action,
            done_by
        )
        VALUES
        (
            %s,
            %s,
            %s
        )
        """,
        (
            job_id,
            f"Job {action_label} by {session['user_name']}",
            session['user_id']
        )
    )

    # Recalculate overall job status
    cursor.execute(
        """
        SELECT status
        FROM job_workers
        WHERE job_id=%s
        """,
        (job_id,)
    )

    all_statuses = [
        r['status']
        for r in cursor.fetchall()
    ]

    overall = derive_overall_status(all_statuses)

    cursor.execute(
        "UPDATE jobs SET status=%s WHERE id=%s",
        (overall, job_id)
    )

    conn.commit()

    cursor.close()
    conn.close()

    socketio.emit(
        'jobs_updated',
        {
            'message':
            f'Job {job_id} worker {worker_id} → {db_status}',
            'job_id': job_id
        }
    )

    return jsonify({
        'message': 'Status updated',
        'overall_status': overall
    })


# ── PATCH /api/jobs/<id>/reschedule ──────────────────────────────
@app.route(
    '/api/jobs/<int:job_id>/reschedule',
    methods=['PATCH']
)
@manager_required
def reschedule_job(job_id):

    data = request.get_json()

    new_start = datetime.fromisoformat(
        data['start_time']
    )

    new_end = datetime.fromisoformat(
        data['end_time']
    )

    if new_end <= new_start:
        return jsonify({
            'error':
            'End time must be after start time'
        }), 400

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT worker_id
        FROM job_workers
        WHERE job_id=%s
        """,
        (job_id,)
    )

    worker_ids = [
        r['worker_id']
        for r in cursor.fetchall()
    ]

    for wid in worker_ids:

        cursor.execute("""
            SELECT j.start_time,
                   j.end_time,
                   j.status AS job_status,
                   w.name AS worker_name
            FROM jobs j
            JOIN job_workers jw ON j.id = jw.job_id
            JOIN workers w ON jw.worker_id = w.id
            WHERE jw.worker_id=%s
              AND j.id!=%s
              AND j.start_time < %s
              AND j.end_time > %s
        """, (
            wid,
            job_id,
            new_end,
            new_start
        ))

        conflict = cursor.fetchone()

        if conflict:

            cursor.close()
            conn.close()

            msg = _conflict_msg(
                conflict['worker_name'],
                conflict['job_status'],
                conflict['start_time'],
                conflict['end_time']
            )

            return jsonify({
                'error': msg
            }), 409

    cursor.execute(
        """
        UPDATE jobs
        SET start_time=%s,
            end_time=%s
        WHERE id=%s
        """,
        (
            new_start,
            new_end,
            job_id
        )
    )

    cursor.execute(
        """
        INSERT INTO job_logs
        (
            job_id,
            action,
            done_by
        )
        VALUES
        (
            %s,
            %s,
            %s
        )
        """,
        (
            job_id,
            f"Rescheduled to "
            f"{new_start.strftime('%d %b %Y %I:%M %p')} "
            f"by {session['user_name']}",
            session['user_id']
        )
    )

    conn.commit()

    # Notify assigned workers
    reschedule_payload = {
        'job_id': job_id,
        'start': new_start.strftime(
            '%d %b %Y %I:%M %p'
        ),
        'end': new_end.strftime(
            '%I:%M %p'
        ),
        'manager': session['user_name'],
        'type': 'reschedule'
    }

    for wid in worker_ids:

        sid = user_sockets.get(wid)

        if sid:

            socketio.emit(
                'task_rescheduled',
                reschedule_payload,
                to=sid
            )

    cursor.close()
    conn.close()

    socketio.emit(
        'jobs_updated',
        {
            'message':
            f'Job {job_id} rescheduled'
        }
    )

    return jsonify({
        'message': 'Job rescheduled'
    })


# ── DELETE /api/jobs/<id> ─────────────────────────────────────────
@app.route(
    '/api/jobs/<int:job_id>',
    methods=['DELETE']
)
@manager_required
def delete_job(job_id):

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    # Verify job exists
    cursor.execute(
        """
        SELECT j.id,
               c.name AS customer
        FROM jobs j
        JOIN customers c
          ON j.customer_id=c.id
        WHERE j.id=%s
        """,
        (job_id,)
    )

    job = cursor.fetchone()

    if not job:

        cursor.close()
        conn.close()

        return jsonify({
            'error': 'Job not found'
        }), 404

    # Collect workers before deletion
    cursor.execute(
        """
        SELECT worker_id
        FROM job_workers
        WHERE job_id=%s
        """,
        (job_id,)
    )

    worker_ids = [
        r['worker_id']
        for r in cursor.fetchall()
    ]

    # Delete child records first
    cursor.execute(
        "DELETE FROM job_logs WHERE job_id=%s",
        (job_id,)
    )

    cursor.execute(
        "DELETE FROM job_workers WHERE job_id=%s",
        (job_id,)
    )

    cursor.execute(
        "DELETE FROM jobs WHERE id=%s",
        (job_id,)
    )

    conn.commit()

    cursor.close()
    conn.close()

    # Notify affected workers
    delete_payload = {
        'job_id': job_id,
        'customer': job['customer'],
        'manager': session['user_name'],
    }

    for wid in worker_ids:

        sid = user_sockets.get(wid)

        if sid:

            socketio.emit(
                'task_deleted',
                delete_payload,
                to=sid
            )

    socketio.emit(
        'jobs_updated',
        {
            'message':
            f'Job {job_id} deleted'
        }
    )

    return jsonify({
        'message':
        'Job deleted successfully'
    })


# ── WebSocket ─────────────────────────────────────────────────────
@socketio.on('connect')
def on_connect():

    print(
        f"Client connected: {request.sid}"
    )


@socketio.on('register')
def on_register(data):

    """
    Workers call this right after connecting so the server can
    map their user_id → socket SID for targeted notifications.
    """

    uid = data.get('user_id')

    if uid:

        user_sockets[uid] = request.sid

        print(
            f"Registered user {uid} → SID {request.sid}"
        )


@socketio.on('disconnect')
def on_disconnect():

    # Clean up SID mapping
    sid = request.sid

    to_remove = [
        uid
        for uid, s in user_sockets.items()
        if s == sid
    ]

    for uid in to_remove:
        del user_sockets[uid]

    print(
        f"Client disconnected: {sid}"
    )


# ── Run Application ──────────────────────────────────────────────
if __name__ == '__main__':
    socketio.run(
        app,
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=True
    )
```
