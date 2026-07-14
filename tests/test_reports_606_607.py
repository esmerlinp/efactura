"""
Test de reportes fiscales DGII (Bloque 5).

Reportes:
  606 (Compras)       — E41, E43, E45, E47
  607 (Ventas)        — E31, E32, E33, E34, E45, E46
  608 (Anulaciones)   — NCF anulados de cualquier tipo
  623 (Gastos Menores) — E41, E43, E45, E47 (montos < RD$50,000)

Verifica:
  - Filtrado correcto por tipo de comprobante
  - Agregación por período (año/mes)
  - Cálculo de montos totales e ITBIS
  - Exclusión de tipos incorrectos
"""
import sys
import os
from collections import defaultdict
from datetime import datetime, timezone
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
TOTAL = 0


def _print(label, status, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    icon = "✅" if status == "PASS" else "❌"
    if status == "PASS":
        PASS += 1
    else:
        FAIL += 1
    print(f"  {label:<40} {icon} {status:<6} {detail[:50]}")


# ---------------------------------------------------------------------------
# Mappings (réplica de los reportes)
# ---------------------------------------------------------------------------
REPORTE_606_TIPOS = {"E41", "E43", "E45", "E47"}
REPORTE_607_TIPOS = {"E31", "E32", "E33", "E34", "E45", "E46"}
REPORTE_608_TIPOS = {"E31", "E32", "E33", "E34", "E41", "E43", "E45", "E46", "E47"}
REPORTE_623_TIPOS = {"E41", "E43", "E45", "E47"}


# ---------------------------------------------------------------------------
# Mock invoice factory
# ---------------------------------------------------------------------------
def make_invoice(ecf_type, encf, subtotal=1000, total=1180, itbis=180,
                 status="Emitida", dgii_status="ACCEPTED",
                 client_rnc="131222222", client_name="CLIENTE TEST",
                 ncf_modificado="", date=None):
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    inv = {
        "encf": encf,
        "ecfType": ecf_type,
        "subtotal": subtotal,
        "total": total,
        "totalITBIS": itbis,
        "montoExento": 0,
        "status": status,
        "dgiiStatus": dgii_status,
        "clientRNC": client_rnc,
        "clientName": client_name,
        "date": date,
        "ncfModificado": ncf_modificado,
        "incomeType": "01",
        "paymentMethod": "Efectivo",
    }
    return inv


def make_expense(ecf_type, encf, subtotal=1000, total=1180, itbis=180,
                 dgii_status="ACCEPTED", provider_rnc="131111111",
                 provider_name="PROVEEDOR TEST", date=None,
                 tipo_gasto="02"):
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    exp = {
        "encf": encf,
        "ecfType": ecf_type,
        "subtotal": subtotal,
        "total": total,
        "totalITBIS": itbis,
        "dgiiStatus": dgii_status,
        "rncEmisor": provider_rnc,
        "providerName": provider_name,
        "date": date,
        "tipoGastoDGII": tipo_gasto,
    }
    return exp


# ---------------------------------------------------------------------------
# Funciones de agregación (réplica simplificada)
# ---------------------------------------------------------------------------
def aggregate_606(expenses):
    """Agrupa gastos elegibles para reporte 606."""
    filtered = [e for e in expenses
                if e["ecfType"] in REPORTE_606_TIPOS
                and e["dgiiStatus"] in ("ACCEPTED", "ACCEPTED_CONDITIONAL")]
    result = {
        "total_count": len(filtered),
        "total_monto": sum(e["total"] for e in filtered),
        "total_itbis": sum(e["totalITBIS"] for e in filtered),
        "by_type": defaultdict(lambda: {"count": 0, "monto": 0, "itbis": 0}),
    }
    for e in filtered:
        t = e["ecfType"]
        result["by_type"][t]["count"] += 1
        result["by_type"][t]["monto"] += e["total"]
        result["by_type"][t]["itbis"] += e["totalITBIS"]
    return result


def aggregate_607(invoices):
    """Agrupa facturas elegibles para reporte 607."""
    filtered = [inv for inv in invoices
                if inv["ecfType"] in REPORTE_607_TIPOS
                and inv["dgiiStatus"] in ("ACCEPTED", "ACCEPTED_CONDITIONAL")
                and inv["status"] not in ("Anulada", "Borrador", "Consolidada")]
    result = {
        "total_count": len(filtered),
        "total_monto": sum(inv["total"] for inv in filtered),
        "total_itbis": sum(inv["totalITBIS"] for inv in filtered),
        "by_type": defaultdict(lambda: {"count": 0, "monto": 0, "itbis": 0}),
    }
    for inv in filtered:
        t = inv["ecfType"]
        result["by_type"][t]["count"] += 1
        result["by_type"][t]["monto"] += inv["total"]
        result["by_type"][t]["itbis"] += inv["totalITBIS"]
    return result


def aggregate_608(invoices):
    """Filtra facturas anuladas para reporte 608."""
    filtered = [inv for inv in invoices
                if inv["status"] == "Anulada"
                and inv["ecfType"] in REPORTE_608_TIPOS]
    return {
        "total_count": len(filtered),
        "by_type": defaultdict(lambda: {"count": 0}),
        "by_cancellation": defaultdict(lambda: {"count": 0}),
    }


def aggregate_623(expenses):
    """Filtra gastos menores para reporte 623."""
    filtered = [e for e in expenses
                if e["ecfType"] in REPORTE_623_TIPOS
                and e["total"] < 50000]
    result = {
        "total_count": len(filtered),
        "total_monto": sum(e["total"] for e in filtered),
        "total_itbis": sum(e["totalITBIS"] for e in filtered),
        "by_type": defaultdict(lambda: {"count": 0, "monto": 0}),
    }
    for e in filtered:
        t = e["ecfType"]
        result["by_type"][t]["count"] += 1
        result["by_type"][t]["monto"] += e["total"]
    return result


# ---------------------------------------------------------------------------
# Escenario 1: Reporte 606 — Compras
# ---------------------------------------------------------------------------
def scenario_1():
    print(f"\n{'='*70}")
    print("  ESCENARIO 1 — Reporte 606 (Compras)")
    print(f"  Tipos: E41, E43, E45, E47")
    print(f"{'='*70}")

    expenses = [
        make_expense("E41", "E410000000001", total=5000, itbis=900),
        make_expense("E43", "E430000000001", total=800, itbis=144),
        make_expense("E45", "E450000000001", total=10000, itbis=0),
        make_expense("E47", "E470000000001", total=2000, itbis=0),
        # E31 no debe estar en 606 (es ventas, no compras)
        make_expense("E31", "E310000000001", total=1180, itbis=180),
        # Rejected no debe contarse
        make_expense("E41", "E410000000002", total=500, itbis=90,
                     dgii_status="REJECTED"),
    ]

    result = aggregate_606(expenses)
    expected_count = 4  # E41, E43, E45, E47 (sin E31, sin REJECTED)
    _print("Solo tipos correctos incluidos",
           "PASS" if result["total_count"] == expected_count else "FAIL",
           f"{result['total_count']}/{expected_count}")

    _print("E31 excluido del 606",
           "PASS" if "E31" not in result["by_type"] else "FAIL", "")

    _print("REJECTED excluido",
           "PASS" if result["by_type"]["E41"]["count"] == 1 else "FAIL",
           f"{result['by_type']['E41']['count']} E41s aceptados")

    expected_monto = 5000 + 800 + 10000 + 2000
    _print("Monto total correcto",
           "PASS" if result["total_monto"] == expected_monto else "FAIL",
           f"{result['total_monto']}/{expected_monto}")


# ---------------------------------------------------------------------------
# Escenario 2: Reporte 607 — Ventas
# ---------------------------------------------------------------------------
def scenario_2():
    print(f"\n{'='*70}")
    print("  ESCENARIO 2 — Reporte 607 (Ventas/Ingresos)")
    print(f"  Tipos: E31, E32, E33, E34, E45, E46")
    print(f"{'='*70}")

    invoices = [
        make_invoice("E31", "E310000000001", total=11800, itbis=1800),
        make_invoice("E32", "E320000000001", total=500, itbis=90),
        make_invoice("E33", "E330000000001", total=200, itbis=36),
        make_invoice("E34", "E340000000001", total=-500, itbis=-90),
        make_invoice("E45", "E450000000001", total=5000, itbis=0),
        make_invoice("E46", "E460000000001", total=10000, itbis=0),
        # E41 no debe estar (es compras)
        make_invoice("E41", "E410000000001", total=1000, itbis=180),
        # Anulada no debe contarse
        make_invoice("E31", "E310000000002", total=1000, itbis=180,
                     status="Anulada"),
        # REJECTED no debe contarse
        make_invoice("E32", "E320000000002", total=300, itbis=54,
                     dgii_status="REJECTED"),
    ]

    result = aggregate_607(invoices)
    expected_count = 6  # E31, E32, E33, E34, E45, E46
    _print("Solo tipos correctos incluidos",
           "PASS" if result["total_count"] == expected_count else "FAIL",
           f"{result['total_count']}/{expected_count}")

    _print("E41 excluido del 607",
           "PASS" if "E41" not in result["by_type"] else "FAIL", "")

    _print("Anuladas excluidas",
           "PASS" if result["by_type"]["E31"]["count"] == 1 else "FAIL",
           "")

    _print("REJECTED excluidas",
           "PASS" if result["by_type"]["E32"]["count"] == 1 else "FAIL",
           "")

    expected_monto = 11800 + 500 + 200 + (-500) + 5000 + 10000
    _print("Monto total correcto",
           "PASS" if result["total_monto"] == expected_monto else "FAIL",
           f"{result['total_monto']}/{expected_monto}")


# ---------------------------------------------------------------------------
# Escenario 3: Reporte 608 — Anulaciones
# ---------------------------------------------------------------------------
def scenario_3():
    print(f"\n{'='*70}")
    print("  ESCENARIO 3 — Reporte 608 (Anulaciones)")
    print(f"  NCF anulados de cualquier tipo")
    print(f"{'='*70}")

    invoices = [
        make_invoice("E31", "E310000000001", status="Anulada"),
        make_invoice("E32", "E320000000001", status="Anulada"),
        make_invoice("E34", "E340000000001", status="Anulada"),
        make_invoice("E41", "E410000000001", status="Anulada"),
        # Emitida no debe estar
        make_invoice("E31", "E310000000002", status="Emitida"),
        # Borrador no debe estar
        make_invoice("E31", "E310000000003", status="Borrador"),
    ]

    result = aggregate_608(invoices)
    _print("Solo anuladas incluidas",
           "PASS" if result["total_count"] == 4 else "FAIL",
           f"{result['total_count']} anuladas")

    all_anuladas = all(
        inv["status"] == "Anulada"
        for inv in invoices if inv["ecfType"] == "E31"
    )
    _print("Emitida/Borrador excluidos",
           "PASS" if result["total_count"] == 4 else "FAIL", "")


# ---------------------------------------------------------------------------
# Escenario 4: Reporte 623 — Gastos Menores
# ---------------------------------------------------------------------------
def scenario_4():
    print(f"\n{'='*70}")
    print("  ESCENARIO 4 — Reporte 623 (Gastos Menores)")
    print(f"  Tipos: E41, E43, E45, E47 | Monto < RD$50,000")
    print(f"{'='*70}")

    expenses = [
        make_expense("E41", "E410000000001", total=5000, itbis=900),
        make_expense("E43", "E430000000001", total=800, itbis=144),
        make_expense("E45", "E450000000001", total=30000, itbis=0),
        # Supera el límite de 50,000 → debe excluirse
        make_expense("E41", "E410000000002", total=60000, itbis=10800,
                     provider_rnc="131333333"),
        make_expense("E47", "E470000000001", total=2000, itbis=0),
        # E31 no debe estar
        make_expense("E31", "E310000000001", total=1000, itbis=180),
    ]

    result = aggregate_623(expenses)
    expected_count = 4  # E41(5000) + E43(800) + E45(30000) + E47(2000)
    _print("Solo tipos y montos correctos",
           "PASS" if result["total_count"] == expected_count else "FAIL",
           f"{result['total_count']}/{expected_count}")

    _print("E41>50,000 excluido",
           "PASS" if result["by_type"]["E41"]["count"] == 1 else "FAIL",
           "")

    _print("E31 excluido del 623",
           "PASS" if "E31" not in result["by_type"] else "FAIL", "")

    expected_monto = 5000 + 800 + 30000 + 2000
    _print("Monto total correcto",
           "PASS" if result["total_monto"] == expected_monto else "FAIL",
           f"{result['total_monto']}/{expected_monto}")


# ---------------------------------------------------------------------------
# Escenario 5: Períodos — Agregación mensual
# ---------------------------------------------------------------------------
def scenario_5():
    print(f"\n{'='*70}")
    print("  ESCENARIO 5 — Agregación por período")
    print(f"  Verificar filtrado por año/mes")
    print(f"{'='*70}")

    invoices = [
        make_invoice("E31", "E310000000001", total=1000,
                     date="2026-01-15"),
        make_invoice("E31", "E310000000002", total=2000,
                     date="2026-01-20"),
        make_invoice("E31", "E310000000003", total=3000,
                     date="2026-02-10"),
        make_invoice("E31", "E310000000004", total=4000,
                     date="2026-03-05"),
    ]

    # Filtrar por enero 2026
    def filter_by_period(invoices, year, month):
        prefix = f"{year}-{month:02d}"
        return [inv for inv in invoices if inv["date"].startswith(prefix)]

    jan = filter_by_period(invoices, 2026, 1)
    feb = filter_by_period(invoices, 2026, 2)
    mar = filter_by_period(invoices, 2026, 3)

    _print("Enero 2026: 2 facturas",
           "PASS" if len(jan) == 2 else "FAIL", f"{len(jan)}")
    _print("Febrero 2026: 1 factura",
           "PASS" if len(feb) == 1 else "FAIL", f"{len(feb)}")
    _print("Marzo 2026: 1 factura",
           "PASS" if len(mar) == 1 else "FAIL", f"{len(mar)}")

    jan_total = sum(inv["total"] for inv in jan)
    _print("Enero monto total: 3000",
           "PASS" if jan_total == 3000 else "FAIL", f"{jan_total}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global PASS, FAIL, TOTAL
    scenario_1()
    scenario_2()
    scenario_3()
    scenario_4()
    scenario_5()

    print(f"\n{'='*70}")
    print(f"  RESUMEN BLOQUE 5 — Reportes DGII (606/607/608/623)")
    print(f"{'='*70}")
    print(f"  {PASS}/{TOTAL} passed")
    if FAIL:
        print(f"  {FAIL} fallos — revisar detalle arriba")
        sys.exit(1)
    print()


if __name__ == "__main__":
    main()
