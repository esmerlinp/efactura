def notify_employee_created(employee: dict):
    if not employee.get("email"):
        return
    try:
        from app.services.mailer import Mailer
        name = employee.get("firstName", employee.get("fullName", "Empleado"))
        Mailer.send(
            app=None, to_email=employee["email"],
            subject="¡Bienvenido al equipo!",
            html_body=f"<h3>Hola {name},</h3><p>Has sido registrado en el sistema de nómina de la empresa.</p>"
                      f"<p>Accede a tu portal en <a href='/mi-perfil'>Mi Perfil</a> para ver tus recibos y datos.</p>",
        )
    except Exception as e:
        print(f"⚠️ notify_employee_created: {e}")


def notify_vacation_approved(employee: dict, request_data: dict):
    if not employee.get("email"):
        return
    try:
        from app.services.mailer import Mailer
        Mailer.send(
            app=None, to_email=employee["email"],
            subject="Vacaciones aprobadas",
            html_body=f"<h3>Hola {employee.get('firstName','')},</h3>"
                      f"<p>Tus vacaciones del {request_data.get('startDate','')} al {request_data.get('endDate','')} "
                      f"({request_data.get('days',0)} días) han sido <strong>aprobadas</strong>.</p>",
        )
    except Exception as e:
        print(f"⚠️ notify_vacation_approved: {e}")


def notify_leave_approved(employee: dict, request_data: dict):
    if not employee.get("email"):
        return
    try:
        from app.services.mailer import Mailer
        Mailer.send(
            app=None, to_email=employee["email"],
            subject="Permiso aprobado",
            html_body=f"<h3>Hola {employee.get('firstName','')},</h3>"
                      f"<p>Tu permiso ({request_data.get('leaveType','')}) del {request_data.get('startDate','')} "
                      f"al {request_data.get('endDate','')} ha sido <strong>aprobado</strong>.</p>",
        )
    except Exception as e:
        print(f"⚠️ notify_leave_approved: {e}")


def notify_birthday_today(employee: dict):
    if not employee.get("email"):
        return
    try:
        from app.services.mailer import Mailer
        Mailer.send(
            app=None, to_email=employee["email"],
            subject="¡Feliz cumpleaños!",
            html_body=f"<h3>¡Feliz cumpleaños, {employee.get('firstName','')}!</h3>"
                      f"<p>De parte de todo el equipo, te deseamos un excelente día.</p>",
        )
    except Exception as e:
        print(f"⚠️ notify_birthday_today: {e}")
