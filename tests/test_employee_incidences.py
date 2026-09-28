"""Tests para EmployeeIncidencesService — vista de incidencias de datos de empleados."""

from unittest.mock import patch

from app.services.employee_incidences_service import (
    get_incidences, get_employee_incidences,
    BLOQUEANTE, REQUERIDO, ADVERTENCIA,
)


def _complete(emp_id="E1", status="activo", **overrides):
    emp = {
        "id": emp_id,
        "code": 1,
        "status": status,
        "fullName": "Juan Pérez",
        "firstName": "Juan",
        "firstLastName": "Pérez",
        "cedula": "00112345678",
        "idType": "cedula",
        "afpProvider": "AFP Popular",
        "tssKey": "001",
        "baseSalary": 50000.0,
        "paymentMethod": "efectivo",
        "occupationCode": "2411",
        "sirlaEducationCode": "4744",
        "sdssNumber": "00112345678",
        "nationality": 1,
        "gender": "masculino",
        "birthDate": "1990-05-15",
        "maritalStatus": "S",
        "hireDate": "2020-01-01",
        "contractType": "tiempo_indefinido",
        "weeklyHours": 44,
        "workShift": 1,
        "vacationGranted": 1,
        "email": "juan@example.com",
        "phone": "8091234567",
        "address": "Calle 1",
        "municipality": "Santo Domingo",
        "emergencyContact": "María",
    }
    emp.update(overrides)
    return emp


def _run(employees, dependents_map=None):
    with patch("app.services.hr_data_service.get_employees", return_value=employees), \
         patch("app.services.hr_data_service.get_dependents_for_employees",
               return_value=dependents_map or {}):
        return get_incidences("C1", sandbox=True)


def _keys(item):
    return {i["key"] for i in item["incidences"]}


def _find(items, emp_id):
    return next(it for it in items if it["employeeId"] == emp_id)


class TestGetIncidences:
    def test_completo_sin_incidencias(self):
        result = _run([_complete()])
        assert result["summary"]["withIncidences"] == 0
        assert _find(result["items"], "E1")["count"] == 0
        assert _find(result["items"], "E1")["blocking"] is False

    def test_bloqueantes_nomina(self):
        emp = _complete(
            afpProvider="", tssKey="", baseSalary=0.0, paymentMethod="",
        )
        result = _run([emp])
        item = _find(result["items"], "E1")
        keys = _keys(item)
        assert {"afp_provider", "tss_key", "base_salary", "payment_method"} <= keys
        assert item["blocking"] is True

    def test_transferencia_sin_cuenta_ni_banco(self):
        emp = _complete(paymentMethod="transferencia", accountNumber="", bank="")
        result = _run([emp])
        assert "bank_account" in _keys(_find(result["items"], "E1"))

    def test_transferencia_completa_sin_incidencia_bancaria(self):
        emp = _complete(paymentMethod="transferencia", accountNumber="123", bank="Popular")
        result = _run([emp])
        assert "bank_account" not in _keys(_find(result["items"], "E1"))

    def test_cedula_invalida(self):
        emp = _complete(cedula="123", idNumber="")
        result = _run([emp])
        assert "cedula" in _keys(_find(result["items"], "E1"))

    def test_requeridos_dgt(self):
        emp = _complete(
            occupationCode="", sirlaEducationCode="", sdssNumber="",
            tssRegistrationNumber="", nationality=0, gender="", birthDate="",
            maritalStatus="", hireDate="", contractType="", weeklyHours=0,
            workShift=0, vacationGranted=0,
        )
        result = _run([emp])
        keys = _keys(_find(result["items"], "E1"))
        assert {
            "occupation_code", "sirla_education_code", "sdss_number",
            "nationality", "gender", "birth_date", "marital_status",
            "hire_date", "contract_type", "weekly_hours", "work_shift",
            "vacation_granted",
        } <= keys

    def test_temporal_sin_dias_ni_salario_diario(self):
        emp = _complete(contractType="tiempo_definido", daysWorked=0, dailySalary=0)
        result = _run([emp])
        assert "temporal_days_salary" in _keys(_find(result["items"], "E1"))

    def test_indefinido_no_exige_dgt5(self):
        emp = _complete(contractType="tiempo_indefinido", daysWorked=0, dailySalary=0)
        result = _run([emp])
        assert "temporal_days_salary" not in _keys(_find(result["items"], "E1"))

    def test_advertencias_contacto(self):
        emp = _complete(email="", phone="", address="", municipality="", emergencyContact="")
        result = _run([emp])
        keys = _keys(_find(result["items"], "E1"))
        assert {"email", "phone", "address", "municipality", "emergency_contact"} <= keys
        item = _find(result["items"], "E1")
        assert all(i["severity"] == ADVERTENCIA for i in item["incidences"])
        assert item["blocking"] is False

    def test_excluye_inactivos_y_suspendidos(self):
        result = _run([
            _complete("E1", status="activo"),
            _complete("E2", status="vacaciones"),
            _complete("E3", status="licencia"),
            _complete("E4", status="inactivo"),
            _complete("E5", status="suspendido"),
        ])
        ids = {i["employeeId"] for i in result["items"]}
        assert ids == {"E1", "E2", "E3"}
        assert result["summary"]["totalActive"] == 3

    def test_dependientes_incompletos(self):
        dependents = {
            "E1": [
                {"id": "D1", "employeeId": "E1", "active": True,
                 "docType": "", "idNumber": "", "relationshipCode": "",
                 "firstName": "Hija", "firstLastName": "Pérez"},
            ]
        }
        result = _run([_complete("E1")], dependents_map=dependents)
        keys = _keys(_find(result["items"], "E1"))
        assert {"dependent_doc_type", "dependent_id", "dependent_relationship"} <= keys

    def test_dependientes_completos_sin_incidencia(self):
        dependents = {
            "E1": [
                {"id": "D1", "employeeId": "E1", "active": True,
                 "docType": "C", "idNumber": "00112345679",
                 "relationshipCode": "hija", "firstName": "Hija"},
            ]
        }
        result = _run([_complete("E1")], dependents_map=dependents)
        keys = _keys(_find(result["items"], "E1"))
        assert not ({"dependent_doc_type", "dependent_id", "dependent_relationship"} & keys)

    def test_summary_by_severity(self):
        result = _run([
            _complete("E1", afpProvider=""),          # bloqueante
            _complete("E2", occupationCode=""),        # requerido
            _complete("E3", email=""),                 # advertencia
        ])
        s = result["summary"]
        assert s["withIncidences"] == 3
        assert s["blocking"] == 1
        assert s["required"] == 1
        assert s["advertencia"] == 1


class TestGetEmployeeIncidences:
    def test_empleado_puntual(self):
        emp = _complete("E1", afpProvider="")
        with patch("app.services.hr_data_service.get_employee", return_value=emp), \
             patch("app.services.hr_data_service.get_dependents_for_employees", return_value={}):
            incidences = get_employee_incidences("C1", "E1", sandbox=True)
        assert any(i["key"] == "afp_provider" for i in incidences)

    def test_empleado_inexistente(self):
        with patch("app.services.hr_data_service.get_employee", return_value=None):
            assert get_employee_incidences("C1", "NOPE", sandbox=True) == []
