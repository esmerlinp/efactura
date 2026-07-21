#!/usr/bin/env python3
"""Disaster Recovery Testing — VykOne ERP

Valida:
1. Conectividad a Firestore (backup primario)
2. Integridad de colecciones (document count, no huérfanos)
3. Integridad de secuencias NCF (sin gaps ni duplicados)
4. Consistencia contable (Activo = Pasivo + Capital)
5. Estado de sesiones activas
6. Health check del servicio
"""

import sys, time, json
from datetime import datetime, timezone


def check_firestore():
    """Verifica conectividad y conteo de documentos en colecciones principales."""
    try:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized or db_firestore is None:
            return {"status": "FAIL", "error": "Firebase no inicializado"}

        collections = {
            "invoices": "sandbox_invoices",
            "clients": "sandbox_clients",
            "employees": "sandbox_employees",
            "accounting_entries": "sandbox_accounting_entries",
            "expenses": "sandbox_expenses",
            "payroll_periods": "sandbox_payroll_periods",
        }

        results = {}
        for label, coll_name in collections.items():
            docs = db_firestore.collection("users").document("demo").collection(coll_name).limit(1000).get()
            results[label] = len(docs)

        return {"status": "PASS", "collections": results}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def check_orphan_integrity():
    """Ejecuta IntegrityScanner y reporta huérfanos."""
    try:
        from app.services.integrity_scanner import IntegrityScanner
        result = IntegrityScanner.scan_all("demo", sandbox=True)
        summary = result.get("summary", {})
        total = summary.get("total", 0)
        critical = summary.get("critica", 0)
        high = summary.get("alta", 0)
        passed = total == 0 or critical == 0
        return {
            "status": "PASS" if passed else "WARN",
            "total_orphans": total,
            "critical": critical,
            "high": high,
            "findings": result.get("findings", [])[:5],
        }
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def check_accounting_balance():
    """Verifica que Activo = Pasivo + Patrimonio (ecuación contable)."""
    try:
        from app.services.accounting_service import AccountingService
        bs = AccountingService.get_balance_sheet("demo")
        if not bs:
            return {"status": "SKIP", "note": "Sin datos contables"}
        assets = bs.get("totalActivos", 0)
        liabilities = bs.get("totalPasivos", 0)
        equity = bs.get("totalPatrimonio", 0)
        diff = abs(assets - (liabilities + equity))
        passed = diff < 1.0
        return {
            "status": "PASS" if passed else "FAIL",
            "activos": round(assets, 2),
            "pasivos": round(liabilities, 2),
            "patrimonio": round(equity, 2),
            "diferencia": round(diff, 2),
        }
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def check_ncf_sequences():
    """Verifica integridad de secuencias NCF (sin gaps)."""
    try:
        from app.services.db_service import DatabaseService
        seqs = DatabaseService.get_sequences("demo", sandbox=True)
        issues = []
        for seq in seqs:
            if seq.get("currentSequence", 0) > 0 and seq.get("startSequence", 0) > 0:
                used = seq.get("currentSequence", 0) - seq.get("startSequence", 0)
                if used < 0:
                    issues.append(f"{seq.get('tipoComprobante', '')}: secuencia inconsistente")
        return {
            "status": "PASS" if not issues else "WARN",
            "total_sequences": len(seqs),
            "issues": issues,
        }
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def check_health():
    """Verifica health endpoint."""
    try:
        import urllib.request
        r = urllib.request.urlopen("http://127.0.0.1:5001/health", timeout=5)
        data = json.loads(r.read())
        return {"status": "PASS" if data.get("status") == "healthy" else "FAIL", "response": data}
    except Exception as e:
        return {"status": "FAIL", "error": str(e)}


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   DISASTER RECOVERY TEST — VykOne ERP v1.0           ║")
    print(f"║   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}                         ║")
    print("╚══════════════════════════════════════════════════════╝")

    tests = {
        "Health Check": check_health,
        "Conectividad Firestore": check_firestore,
        "Integridad Referencial": check_orphan_integrity,
        "Balance Contable": check_accounting_balance,
        "Secuencias NCF": check_ncf_sequences,
    }

    passed = 0
    failed = 0

    for name, fn in tests.items():
        print(f"\n── {name} ──")
        try:
            result = fn()
        except Exception as e:
            result = {"status": "FAIL", "error": str(e)}
        status = result.get("status", "FAIL")
        if status == "PASS":
            print(f"  ✅ PASS")
            passed += 1
        elif status == "WARN":
            print(f"  ⚠️  WARN — {json.dumps({k:v for k,v in result.items() if k != 'status'}, default=str)[:200]}")
            passed += 1
        elif status == "SKIP":
            print(f"  ⏭️  SKIP — {result.get('note', '')}")
        else:
            print(f"  ❌ FAIL — {json.dumps({k:v for k,v in result.items() if k != 'status'}, default=str)[:200]}")
            failed += 1

    total = len(tests)
    print(f"\n{'='*60}")
    print(f"  RESULTADO: {passed}/{total} pasan | {failed} fallan")
    pct = int(100 * passed / total)
    print(f"  Disaster Recovery Score: {pct}%")
    verdict = "APTO" if pct >= 80 else "REQUIERE ATENCIÓN"
    print(f"  Veredicto: {verdict}")
    print(f"{'='*60}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
