from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_mysqldb import MySQL
import pymysql
import os
import random
from functools import wraps
import base64
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
load_dotenv()


# Initialize Flask app
app = Flask(__name__)

# Load environment variables or use default values
app.config['MYSQL_HOST'] = os.getenv("DB_HOST", "localhost")
app.config['MYSQL_USER'] = os.getenv("DB_USER", "root")
app.config['MYSQL_PASSWORD'] = os.getenv("DB_PASSWORD", "")
app.config['MYSQL_DB'] = os.getenv("DB_NAME", "payroll")
app.secret_key = os.getenv("SECRET_KEY", "09067238100")

# Set your API key here or load from env
API_KEY = os.getenv('09067238100', 'jopri')

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip API key check for HTML page requests (browsers)
        if request.accept_mimetypes.accept_html:
            return f(*args, **kwargs)

        # Only enforce for JSON/api requests
        key = request.headers.get('x-api-key')
        if not key or key != API_KEY:
            return jsonify({"error": "Unauthorized access, invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated


# Initialize MySQL with Flask
mysql = MySQL(app)

# Helper: Use PyMySQL for DictCursor support
def get_db_connection():
    return pymysql.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        db=app.config['MYSQL_DB'],
        cursorclass=pymysql.cursors.DictCursor
    )

# Decorator: Require login
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ----------------- Routes -----------------

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        division = request.form['division']
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username=%s AND division=%s", (username, division))
            user = cursor.fetchone()
        conn.close()

        if user and user['password'] == password:
            session.update({'user_id': user['id'], 'username': user['username'], 'division': user['division']})
            return redirect(url_for('admin_home'))
        error = 'Invalid credentials. Please try again.'
    return render_template('login.html', error=error)

@app.route('/create_account', methods=['GET', 'POST'])
def create_account():
    if request.method == 'POST':
        division = request.form['division']
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            flash('Username already exists.', 'error')
            return redirect(url_for('create_account'))

        for _ in range(5):
            emp_id = f"{division[:3]}-{random.randint(10,99)}"
            cur.execute("SELECT * FROM users WHERE empId = %s", (emp_id,))
            if not cur.fetchone():
                break
        else:
            flash('Failed to generate employee ID.', 'error')
            return redirect(url_for('create_account'))

        cur.execute("INSERT INTO users (empId, division, username, password) VALUES (%s, %s, %s, %s)",
                    (emp_id, division, username, password))
        mysql.connection.commit()
        flash(f'Account created! Employee ID: {emp_id}', 'success')
        return redirect(url_for('login'))
    return render_template('create_account.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            flash('Password reset link sent.', 'info')
        else:
            flash('Username not found.', 'danger')
        cur.close()
    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/admin_home')
@require_api_key
@login_required
def admin_home():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total_staff FROM staff_information WHERE status = %s", ('Hired',))
        total_staff = cursor.fetchone()['total_staff']

        cursor.execute("SELECT SUM(net_pay) AS total_salary FROM payroll")
        total_salary = cursor.fetchone()['total_salary']

        cursor.execute("SELECT IFNULL(SUM(deduction_amount), 0) AS total_deductions FROM deductions")
        total_deductions = cursor.fetchone()['total_deductions']

        cursor.execute("SELECT IFNULL(SUM(amount), 0) AS total_allowance FROM allowance")
        total_allowance = cursor.fetchone()['total_allowance']
    conn.close()
    return render_template('admin_homepage.html', total_staff=total_staff,
                           total_salary=total_salary,
                           total_deductions=total_deductions,
                           total_allowance=total_allowance)

@app.route('/manage_employees', methods=['GET', 'POST'])
@require_api_key
@login_required
def manage_employees():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        if request.method == 'POST':
            emp_id = request.form.get('employee_id')
            cursor.execute("UPDATE staff_information SET status = 'fired' WHERE id = %s", (emp_id,))
            conn.commit()
            flash(f'Employee ID {emp_id} fired.', 'success')
            return redirect(url_for('manage_employees'))

        cursor.execute("SELECT id, first_name, surname FROM staff_information WHERE status = 'hired'")
        staff_list = cursor.fetchall()
    conn.close()
    return render_template('manage_employees.html', staff_list=staff_list)

@app.route('/')
@require_api_key
def index():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, first_name, surname FROM staff_information")
            staff_list = cursor.fetchall()
    finally:
        conn.close()
    return render_template('index.html', staff_list=staff_list)

@app.route('/get_staff_details')
@require_api_key
def get_staff_details():
    staff_id = request.args.get('id')
    if not staff_id:
        return jsonify({'error': 'No id provided'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM staff_information WHERE id = %s", (staff_id,))
            staff = cursor.fetchone()
            if not staff:
                return jsonify({'error': 'Staff not found'}), 404
            
            # Encode image to base64 if exists
            if staff.get('image'):
                staff['image'] = base64.b64encode(staff['image']).decode('utf-8')
            else:
                staff['image'] = None

            # Format dates as strings
            if staff.get('dob'):
                staff['dob'] = staff['dob'].strftime('%Y-%m-%d')
            if staff.get('date_hired'):
                staff['date_hired'] = staff['date_hired'].strftime('%Y-%m-%d')

            return jsonify(staff)
    finally:
        conn.close()

@app.route('/payroll_reports')
@require_api_key
def payroll_reports():
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch all allowance, deductions, payroll data as usual
    cur.execute("SELECT * FROM allowance")
    allowance = cur.fetchall()

    cur.execute("SELECT * FROM deductions")
    deductions = cur.fetchall()

    cur.execute("SELECT * FROM payroll")
    payroll = cur.fetchall()

    # New query: SUM deduction_amount
    cur.execute("SELECT SUM(deduction_amount) AS total_deductions FROM deductions")
    total_deduction_row = cur.fetchone()
    total_deductions = total_deduction_row['total_deductions'] or 0  # fallback to 0 if None

    # Calculate totals for other fields
    total_allowance = sum(float(row['amount']) for row in allowance)
    total_salary = sum(float(row['base_salary']) for row in payroll)
    remaining_salary = total_salary - float(total_deductions)
    total_net = sum(float(row['net_pay']) for row in payroll)

    total = {
        'total_allowance': total_allowance,
        'total_deductions': float(total_deductions),
        'remaining_salary': remaining_salary,
        'total_net': total_net,
    }

    conn.close()
    return render_template('payroll_reports.html', allowance=allowance, deductions=deductions, payroll=payroll, total=total)

@app.route('/accounting', methods=['GET', 'POST'])
@require_api_key
@login_required
def accounting():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT empId, first_name, surname, salary FROM staff_information WHERE status = 'hired'")
        employees = cursor.fetchall()

    if request.method == 'POST':
        emp_id = request.form.get('empId')

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM staff_information WHERE empId = %s", (emp_id,))
            employee = cursor.fetchone()

            if not employee:
                flash("Employee not found.", "danger")
                return redirect(url_for('accounting'))

            if 'allowance_submit' in request.form:
                allowance_type = request.form.get('allowance_type')
                allowance_amount = float(request.form.get('allowance_amount'))
                created_by = session.get('username')
                first_name = employee['first_name']
                surname = employee['surname']

                cursor.execute(
                    "INSERT INTO allowance (empId, first_name, surname, allowance_type, amount, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                    (emp_id, first_name, surname, allowance_type, allowance_amount, created_by)
                )
                conn.commit()
                flash(f'Allowance added for {first_name} {surname}', 'success')

            elif 'deduction_submit' in request.form:
                deduction_type = request.form.get('deduction_type')
                deduction_amount = float(request.form.get('deduction_amount'))
                created_by = session.get('username')
                first_name = employee['first_name']
                surname = employee['surname']

                cursor.execute(
                    "INSERT INTO deductions (empId, first_name, surname, deduction_type, deduction_amount, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                    (emp_id, first_name, surname, deduction_type, deduction_amount, created_by)
                )
                conn.commit()
                flash(f'Deduction added for {first_name} {surname}', 'success')

        return redirect(url_for('accounting'))

    return render_template('accounting.html', employees=employees)

@app.route('/add_employee', methods=['GET', 'POST'])
@require_api_key
@login_required
def add_employee():
    if request.method == 'POST':
        data = request.form
        empId = data.get('empId')
        first_name = data.get('first_name')
        surname = data.get('surname')
        middle_initial = data.get('middle_initial')
        dob = data.get('dob')
        division = data.get('division')
        department = data.get('department')
        position = data.get('position')
        status = data.get('status')
        date_hired = data.get('date_hired')
        salary = data.get('salary')
        photo = request.files.get('photo')

        image_data = photo.read() if photo else None

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO staff_information (empId, first_name, surname, middle_initial, dob, division, department, position, status, date_hired, salary, image)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (empId, first_name, surname, middle_initial, dob, division, department, position, status, date_hired, salary, image_data))
            conn.commit()
        conn.close()

        flash(f'Employee {first_name} {surname} added successfully.', 'success')
        return redirect(url_for('manage_employees'))

    return render_template('add_employee.html')

@app.route('/edit_employee/<int:id>', methods=['GET', 'POST'])
@require_api_key
@login_required
def edit_employee(id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        if request.method == 'POST':
            data = request.form
            first_name = data.get('first_name')
            surname = data.get('surname')
            middle_initial = data.get('middle_initial')
            dob = data.get('dob')
            division = data.get('division')
            department = data.get('department')
            position = data.get('position')
            status = data.get('status')
            date_hired = data.get('date_hired')
            salary = data.get('salary')
            photo = request.files.get('photo')

            image_data = photo.read() if photo else None

            # Build update query conditionally for image
            if image_data:
                cursor.execute("""
                    UPDATE staff_information SET first_name=%s, surname=%s, middle_initial=%s, dob=%s, division=%s, department=%s,
                    position=%s, status=%s, date_hired=%s, salary=%s, image=%s WHERE id=%s
                """, (first_name, surname, middle_initial, dob, division, department, position, status, date_hired, salary, image_data, id))
            else:
                cursor.execute("""
                    UPDATE staff_information SET first_name=%s, surname=%s, middle_initial=%s, dob=%s, division=%s, department=%s,
                    position=%s, status=%s, date_hired=%s, salary=%s WHERE id=%s
                """, (first_name, surname, middle_initial, dob, division, department, position, status, date_hired, salary, id))
            conn.commit()

            flash('Employee updated successfully.', 'success')
            return redirect(url_for('manage_employees'))

        cursor.execute("SELECT * FROM staff_information WHERE id = %s", (id,))
        employee = cursor.fetchone()
    conn.close()

    if employee and employee.get('image'):
        employee['image'] = base64.b64encode(employee['image']).decode('utf-8')
    else:
        employee['image'] = None

    return render_template('edit_employee.html', employee=employee)

# ----------------------------------------

if __name__ == '__main__':
    app.run(debug=True)
