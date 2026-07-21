#!/usr/bin/env python3
"""Data Migration Framework — VykOne ERP

Importa datos desde CSV/JSON a Firestore con validación.
Soporta: empleados, clientes, catálogo contable, proveedores, saldos iniciales.

Formato esperado:
  employees.csv: firstName,lastName,idNumber,position,salary,hireDate,...
  clients.csv: rnc,razonSocial,email,telefono,direccion,...
  chart_of_accounts.csv: code,name,group,type,nature,usage,...
  initial_balances.csv: accountCode,debit,credit,date,...
"""

import csv, json, sys, os, re, uuid
from datetime import datetime, timezone
from typing import List, Dict


class DataMigrationService:

    @staticmethod
    def parse_csv(filepath: str) -> List[Dict]:
        rows = []
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items() if k})
        return rows

    @classmethod
    def import_employees(cls, owner_uid: str, filepath: str, sandbox: bool = True) -> Dict:
        from app.services.db_service import DatabaseService
        rows = cls.parse_csv(filepath)
        result = {"total": len(rows), "imported": 0, "errors": []}
        for row in rows:
            try:
                emp_id = str(uuid.uuid4())
                emp = {
                    "id": emp_id,
                    "firstName": row.get("firstName", ""),
                    "lastName": row.get("lastName", ""),
                    "fullName": f"{row.get('firstName', '')} {row.get('lastName', '')}".strip(),
                    "idNumber": (row.get("idNumber") or row.get("cedula", "")).replace("-", ""),
                    "cedula": (row.get("idNumber") or row.get("cedula", "")).replace("-", ""),
                    "position": row.get("position", ""),
                    "baseSalary": float(row.get("salary", 0) or 0),
                    "salary": float(row.get("salary", 0) or 0),
                    "hireDate": row.get("hireDate", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "status": "activo",
                    "contractType": row.get("contractType", "Indefinido"),
                    "email": row.get("email", ""),
                    "phone": row.get("phone", ""),
                    "address": row.get("address", ""),
                    "branchId": row.get("branchId", "default-sucursal-principal"),
                    "workday": row.get("workday", "completa"),
                    "paymentMethod": row.get("paymentMethod", "Transferencia"),
                    "nationality": 1,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
                DatabaseService.save_employee(owner_uid, emp_id, emp, sandbox=sandbox)
                result["imported"] += 1
            except Exception as e:
                result["errors"].append(f"Fila con cédula {row.get('idNumber','?')}: {e}")
        return result

    @classmethod
    def import_clients(cls, owner_uid: str, filepath: str, sandbox: bool = True) -> Dict:
        from app.services.db_service import DatabaseService
        rows = cls.parse_csv(filepath)
        result = {"total": len(rows), "imported": 0, "errors": []}
        for row in rows:
            try:
                client_id = str(uuid.uuid4())
                client = {
                    "id": client_id,
                    "rnc": (row.get("rnc") or "").strip(),
                    "razonSocial": (row.get("razonSocial") or row.get("name", "")).strip(),
                    "email": row.get("email", ""),
                    "telefono": row.get("telefono", ""),
                    "direccion": row.get("direccion", ""),
                    "pipelineStage": "Cliente Activo",
                    "creditLimit": float(row.get("creditLimit", 0) or 0),
                    "customer_category": row.get("customer_category", "NORMAL"),
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                }
                DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
                result["imported"] += 1
            except Exception as e:
                result["errors"].append(f"Fila {row.get('razonSocial','?')}: {e}")
        return result

    @classmethod
    def import_chart_of_accounts(cls, owner_uid: str, filepath: str, sandbox: bool = True) -> Dict:
        from app.services.db_service import DatabaseService
        rows = cls.parse_csv(filepath)
        result = {"total": len(rows), "imported": 0, "errors": []}
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        existing_codes = {a.get("code", "") for a in accounts}
        for row in rows:
            try:
                code = row.get("code", "").strip()
                if not code or code in existing_codes:
                    continue
                acc_id = str(uuid.uuid4())
                account = {
                    "id": acc_id,
                    "code": code,
                    "name": row.get("name", ""),
                    "group": row.get("group", "activos"),
                    "type": row.get("type", "movimiento"),
                    "nature": row.get("nature", "deudora"),
                    "usage": row.get("usage"),
                    "level": int(row.get("level", 3)),
                    "parentId": row.get("parentId"),
                    "orderIdx": int(row.get("orderIdx", 99)),
                    "description": row.get("description", ""),
                    "isSystem": False,
                }
                DatabaseService.save_chart_of_account(owner_uid, acc_id, account, sandbox=sandbox)
                result["imported"] += 1
            except Exception as e:
                result["errors"].append(f"Cuenta {row.get('code','?')}: {e}")
        return result

    @classmethod
    def import_initial_balances(cls, owner_uid: str, filepath: str, sandbox: bool = True) -> Dict:
        from app.services.db_service import DatabaseService
        from app.services.accounting_service import AccountingService
        rows = cls.parse_csv(filepath)
        result = {"total": len(rows), "imported": 0, "errors": []}
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        code_to_id = {a.get("code", ""): a.get("id", "") for a in accounts}
        lines = []
        for row in rows:
            try:
                acc_code = row.get("accountCode", "").strip()
                acc_id = code_to_id.get(acc_code)
                if not acc_id:
                    result["errors"].append(f"Cuenta {acc_code} no encontrada")
                    continue
                debit = float(row.get("debit", 0) or 0)
                credit = float(row.get("credit", 0) or 0)
                lines.append({
                    "accountId": acc_id,
                    "accountCode": acc_code,
                    "accountName": row.get("accountName", ""),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "description": f"Saldo inicial — {acc_code}",
                })
            except Exception as e:
                result["errors"].append(f"Línea {acc_code}: {e}")
        if lines:
            try:
                entry = AccountingService.generate_entry(owner_uid, {
                    "entryType": "initial_balance",
                    "date": rows[0].get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "concept": "Saldos iniciales importados",
                    "referenceType": "migration",
                    "referenceId": "initial-balances-migration",
                    "referenceNumber": "MIG-001",
                    "lines": lines,
                    "createdBy": "migration",
                }, sandbox=sandbox)
                result["imported"] = len(lines)
                result["entryId"] = entry.get("id", "") if entry else ""
            except Exception as e:
                result["errors"].append(f"Error generando asiento: {e}")
        return result

    @classmethod
    def validate_import(cls, owner_uid: str, entity_type: str, sandbox: bool = True) -> Dict:
        from app.services.db_service import DatabaseService
        if entity_type == "employees":
            count = len(DatabaseService.get_employees(owner_uid, sandbox=sandbox))
        elif entity_type == "clients":
            count = len(DatabaseService.get_clients(owner_uid, sandbox=sandbox))
        elif entity_type == "accounts":
            count = len(DatabaseService.get_chart_of_accounts(owner_uid))
        else:
            count = 0
        return {"entity_type": entity_type, "total_records": count}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python data_migration.py <owner_uid> <csv_dir>")
        print("")
        print("Expected CSV files in <csv_dir>:")
        print("  employees.csv, clients.csv, chart_of_accounts.csv, initial_balances.csv")
        sys.exit(1)

    owner_uid = sys.argv[1]
    csv_dir = sys.argv[2]
    sandbox = True

    svc = DataMigrationService()

    for fname, method in [
        ("employees.csv", svc.import_employees),
        ("clients.csv", svc.import_clients),
        ("chart_of_accounts.csv", svc.import_chart_of_accounts),
        ("initial_balances.csv", svc.import_initial_balances),
    ]:
        fpath = os.path.join(csv_dir, fname)
        if os.path.exists(fpath):
            print(f"\n── Importando {fname}...")
            result = method(owner_uid, fpath, sandbox)
            print(f"    Total: {result['total']} | Importado: {result['imported']} | Errores: {len(result['errors'])}")
            if result["errors"]:
                for e in result["errors"][:5]:
                    print(f"    ⚠️  {e}")
        else:
            print(f"\n── {fname}: archivo no encontrado, omitiendo")
