"""Servicio de Kardex Valorizado Continuo (FIFO).

Proporciona la vista cronológica inmutable y auditada de todos los movimientos
de inventario con su respectiva valorización monetaria.

Fuentes de verdad:
- inventory_transactions: movimientos físicos inmutables y detalle de capas FIFO consumidas.
- inventory_cost_ledger: capas de costo activas y saldo de valorización.
- inventory_stock: existencia física actual por almacén.
- items.totalStock: vista materializada del catálogo (utilizada únicamente para conciliación).
"""

import io
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

from app.services.db_service import _company_coll, db_firestore, firebase_initialized, DatabaseService


class KardexService:
    """Motor de cálculo, auditoría y exportación del Kardex Valorizado Continuo."""

    TYPE_SORT_PRIORITY = {
        "ENTRADA": 0,
        "TRANSFERENCIA": 1,
        "AJUSTE": 2,
        "SALIDA": 3,
    }

    # ── 1. CONSULTA Y PROCESAMIENTO DE MOVIMIENTOS ───────────────────────────

    @classmethod
    def get_kardex(
        cls,
        company_id: str,
        item_id: str,
        warehouse_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calcula el Kardex cronológico continuo para un artículo.
        
        Soporta filtrado por almacén y por rango de fechas (dateFrom / dateTo).
        Calcula el saldo inicial acumulado antes de dateFrom y los saldos continuos
        del período.
        """
        if not company_id or not item_id:
            return cls._empty_kardex_response(company_id, item_id, warehouse_id, date_from, date_to)

        # 1. Obtener datos del artículo del catálogo
        item_info = cls._get_item_info(company_id, item_id, sandbox=sandbox, owner_uid=owner_uid)
        
        # 2. Obtener almacenes para mapeo de nombres legibles
        warehouses = DatabaseService.get_warehouses(owner_uid or "", sandbox=sandbox, company_id=company_id)
        wh_map = {w["id"]: w.get("name", w["id"]) for w in warehouses}
        warehouse_name = wh_map.get(warehouse_id, "Todos los Almacenes") if warehouse_id else "Todos los Almacenes"

        # 3. Leer todas las transacciones históricas del artículo para la empresa
        raw_txs = cls._fetch_item_transactions(company_id, item_id, sandbox=sandbox, owner_uid=owner_uid)

        # 4. Proyectar y normalizar transacciones según el filtro de almacén
        projected_rows = []
        for tx in raw_txs:
            rows = cls._project_transaction_rows(tx, warehouse_id=warehouse_id, wh_map=wh_map)
            projected_rows.extend(rows)

        # 5. Ordenar determinísticamente: fecha ASC -> createdAt ASC -> prioridad tipo -> id
        projected_rows.sort(key=cls._sort_key)

        # 6. Separar saldo inicial (antes de date_from) y movimientos del período
        init_qty = 0.0
        init_value = 0.0

        period_movements = []
        running_qty = 0.0
        running_value = 0.0

        period_in_qty = 0.0
        period_in_val = 0.0
        period_out_qty = 0.0
        period_out_val = 0.0

        df_clean = (date_from or "").strip()
        dt_clean = (date_to or "").strip()
        if dt_clean and len(dt_clean) == 10:
            dt_clean = f"{dt_clean}T23:59:59.999999Z"

        for row in projected_rows:
            row_date = row.get("date") or row.get("createdAt") or ""
            in_q = float(row.get("inQty", 0.0))
            in_v = float(row.get("inTotalValue", 0.0))
            out_q = float(row.get("outQty", 0.0))
            out_v = float(row.get("outTotalValue", 0.0))

            # ¿Es anterior a date_from? -> Acumular en Saldo Inicial
            if df_clean and row_date < df_clean:
                init_qty += (in_q - out_q)
                init_value += (in_v - out_v)
                continue

            # ¿Es posterior a date_to? -> Ignorar para este período
            if dt_clean and row_date > dt_clean:
                continue

            # Movimiento dentro del período
            if not period_movements:
                running_qty = init_qty
                running_value = init_value

            running_qty += (in_q - out_q)
            running_value += (in_v - out_v)

            running_qty = round(running_qty, 4)
            running_value = round(running_value, 2)
            if running_qty <= 0.0:
                running_qty = 0.0
                running_value = 0.0

            unit_cost_balance = round(running_value / running_qty, 4) if running_qty > 0 else 0.0

            period_in_qty += in_q
            period_in_val += in_v
            period_out_qty += out_q
            period_out_val += out_v

            period_row = dict(row)
            period_row["balanceQty"] = running_qty
            period_row["balanceTotalValue"] = running_value
            period_row["balanceUnitCost"] = unit_cost_balance
            period_movements.append(period_row)

        if not period_movements:
            running_qty = init_qty
            running_value = init_value

        init_unit_cost = round(init_value / init_qty, 4) if init_qty > 0 else 0.0
        final_unit_cost = round(running_value / running_qty, 4) if running_qty > 0 else 0.0

        return {
            "companyId": company_id,
            "itemId": item_id,
            "item": item_info,
            "warehouseId": warehouse_id,
            "warehouseName": warehouse_name,
            "dateFrom": date_from,
            "dateTo": date_to,
            "initialBalance": {
                "quantity": round(init_qty, 4),
                "totalValue": round(init_value, 2),
                "unitCost": init_unit_cost,
                "date": date_from or ""
            },
            "movements": period_movements,
            "finalBalance": {
                "quantity": round(running_qty, 4),
                "totalValue": round(running_value, 2),
                "unitCost": final_unit_cost
            },
            "periodTotals": {
                "inQuantity": round(period_in_qty, 4),
                "inTotalValue": round(period_in_val, 2),
                "outQuantity": round(period_out_qty, 4),
                "outTotalValue": round(period_out_val, 2)
            }
        }

    # ── 2. RESUMEN Y CONCILIACIÓN CON LEDGER Y STOCK ────────────────────────

    @classmethod
    def get_kardex_summary(
        cls,
        company_id: str,
        item_id: Optional[str] = None,
        warehouse_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Genera el resumen de Kardex con conciliación obligatoria entre:
        1. Saldo final del Kardex
        2. Existencia física actual (inventory_stock)
        3. Valorización de capas FIFO activas (inventory_cost_ledger)
        4. Vista materializada del catálogo (items.totalStock)
        """
        if item_id:
            kardex_data = cls.get_kardex(
                company_id=company_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                date_from=date_from,
                date_to=date_to,
                sandbox=sandbox,
                owner_uid=owner_uid
            )
            reconciliation = cls._reconcile_item(
                company_id=company_id,
                item_id=item_id,
                kardex_data=kardex_data,
                warehouse_id=warehouse_id,
                sandbox=sandbox,
                owner_uid=owner_uid
            )
            kardex_data["reconciliation"] = reconciliation
            return kardex_data

        # Resumen consolidado para todos los artículos de tipo "Bien" de la empresa
        items = cls._get_all_company_items(company_id, sandbox=sandbox, owner_uid=owner_uid)
        warehouses = DatabaseService.get_warehouses(owner_uid or "", sandbox=sandbox, company_id=company_id)
        wh_map = {w["id"]: w.get("name", w["id"]) for w in warehouses}

        summary_items = []
        total_initial_value = 0.0
        total_in_value = 0.0
        total_out_value = 0.0
        total_final_value = 0.0
        discrepancies_count = 0

        for it in items:
            if it.get("type", "Bien") != "Bien":
                continue
            i_id = it["id"]
            k_res = cls.get_kardex(
                company_id=company_id,
                item_id=i_id,
                warehouse_id=warehouse_id,
                date_from=date_from,
                date_to=date_to,
                sandbox=sandbox,
                owner_uid=owner_uid
            )
            reconcil = cls._reconcile_item(
                company_id=company_id,
                item_id=i_id,
                kardex_data=k_res,
                warehouse_id=warehouse_id,
                sandbox=sandbox,
                owner_uid=owner_uid
            )

            if reconcil.get("status") != "OK":
                discrepancies_count += 1

            init_b = k_res["initialBalance"]
            fin_b = k_res["finalBalance"]
            p_tot = k_res["periodTotals"]

            total_initial_value += init_b["totalValue"]
            total_in_value += p_tot["inTotalValue"]
            total_out_value += p_tot["outTotalValue"]
            total_final_value += fin_b["totalValue"]

            summary_items.append({
                "itemId": i_id,
                "itemCode": it.get("code") or it.get("reference", ""),
                "itemName": it.get("name", ""),
                "unit": it.get("unit", "Unidad"),
                "initialQty": init_b["quantity"],
                "initialValue": init_b["totalValue"],
                "periodInQty": p_tot["inQuantity"],
                "periodInValue": p_tot["inTotalValue"],
                "periodOutQty": p_tot["outQuantity"],
                "periodOutValue": p_tot["outTotalValue"],
                "finalQty": fin_b["quantity"],
                "finalValue": fin_b["totalValue"],
                "finalUnitCost": fin_b["unitCost"],
                "stockQty": reconcil.get("stockQty", 0.0),
                "ledgerValue": reconcil.get("ledgerValue", 0.0),
                "qtyDifference": reconcil.get("qtyDifference", 0.0),
                "valueDifference": reconcil.get("valueDifference", 0.0),
                "reconciliationStatus": reconcil.get("status", "OK"),
            })

        return {
            "companyId": company_id,
            "warehouseId": warehouse_id,
            "warehouseName": wh_map.get(warehouse_id, "Todos los Almacenes") if warehouse_id else "Todos los Almacenes",
            "dateFrom": date_from,
            "dateTo": date_to,
            "totalItems": len(summary_items),
            "discrepanciesCount": discrepancies_count,
            "overallStatus": "OK" if discrepancies_count == 0 else "WARNING",
            "totals": {
                "initialValue": round(total_initial_value, 2),
                "inValue": round(total_in_value, 2),
                "outValue": round(total_out_value, 2),
                "finalValue": round(total_final_value, 2)
            },
            "items": summary_items
        }

    # ── 3. EXPORTACIÓN EXCEL PROFESIONAL (OPENPYXL) ─────────────────────────

    @classmethod
    def export_kardex_excel(
        cls,
        company_id: str,
        item_id: str,
        warehouse_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> io.BytesIO:
        """Genera un archivo Excel (.xlsx) con formato corporativo del Kardex."""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        kardex = cls.get_kardex_summary(
            company_id=company_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            date_from=date_from,
            date_to=date_to,
            sandbox=sandbox,
            owner_uid=owner_uid
        )

        item = kardex.get("item", {})
        item_name = item.get("name", "Artículo")
        item_code = item.get("code") or item.get("reference", "")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Kardex Valorizado"
        ws.views.sheetView[0].showGridLines = True

        C_HEADER_DARK = "1E293B"     # Slate 800
        C_HEADER_LIGHT = "F1F5F9"    # Slate 100
        C_BORDER = "CBD5E1"          # Slate 300

        font_title = Font(name="Segoe UI", size=15, bold=True, color="0F172A")
        font_subtitle = Font(name="Segoe UI", size=10, color="475569")
        font_section = Font(name="Segoe UI", size=10, bold=True, color=C_HEADER_DARK)
        font_header = Font(name="Segoe UI", size=9, bold=True, color="FFFFFF")
        font_subhead = Font(name="Segoe UI", size=9, bold=True, color=C_HEADER_DARK)
        font_data = Font(name="Segoe UI", size=9, color="1E293B")
        font_data_bold = Font(name="Segoe UI", size=9, bold=True, color="1E293B")
        font_kpi_val = Font(name="Segoe UI", size=12, bold=True, color="0F172A")
        font_kpi_lbl = Font(name="Segoe UI", size=8, color="64748B")

        thin_side = Side(border_style="thin", color=C_BORDER)
        med_side = Side(border_style="medium", color=C_HEADER_DARK)
        border_cell = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
        border_top_thick = Border(top=thin_side, bottom=med_side)

        fill_header = PatternFill(start_color=C_HEADER_DARK, end_color=C_HEADER_DARK, fill_type="solid")
        fill_subhead_in = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
        fill_subhead_out = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        fill_subhead_bal = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")
        fill_kpi = PatternFill(start_color=C_HEADER_LIGHT, end_color=C_HEADER_LIGHT, fill_type="solid")

        # 1. Título y Encabezado de Empresa
        ws["A1"] = "REPORTE DE KARDEX VALORIZADO CONTINUO (FIFO)"
        ws["A1"].font = font_title
        ws["A2"] = f"Artículo: [{item_code}] {item_name} | Almacén: {kardex.get('warehouseName')} | Método: FIFO"
        ws["A2"].font = font_subtitle
        period_str = f"Período: {date_from or 'Inicio'} al {date_to or 'Actual'}"
        ws["A3"] = f"{period_str} | Generado: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}"
        ws["A3"].font = font_subtitle

        # 2. Bloque KPI Cards (Fila 5 a 6)
        kpi_cards = [
            ("Saldo Inicial", f"{kardex['initialBalance']['quantity']:,.2f} uds", f"RD$ {kardex['initialBalance']['totalValue']:,.2f}", 1),
            ("Entradas Período", f"{kardex['periodTotals']['inQuantity']:,.2f} uds", f"RD$ {kardex['periodTotals']['inTotalValue']:,.2f}", 4),
            ("Salidas (COGS)", f"{kardex['periodTotals']['outQuantity']:,.2f} uds", f"RD$ {kardex['periodTotals']['outTotalValue']:,.2f}", 7),
            ("Saldo Final", f"{kardex['finalBalance']['quantity']:,.2f} uds", f"RD$ {kardex['finalBalance']['totalValue']:,.2f}", 10),
        ]
        for title, q_str, v_str, col_idx in kpi_cards:
            ws.merge_cells(start_row=5, start_column=col_idx, end_row=5, end_column=col_idx+2)
            ws.merge_cells(start_row=6, start_column=col_idx, end_row=6, end_column=col_idx+2)
            c_top = ws.cell(row=5, column=col_idx, value=f"{title}: {q_str}")
            c_top.font = font_kpi_lbl
            c_top.fill = fill_kpi
            c_top.alignment = Alignment(horizontal="center", vertical="center")
            c_bot = ws.cell(row=6, column=col_idx, value=v_str)
            c_bot.font = font_kpi_val
            c_bot.fill = fill_kpi
            c_bot.alignment = Alignment(horizontal="center", vertical="center")

        # 3. Encabezados de Tabla (Filas 8 y 9)
        ws.merge_cells("A8:E8")
        ws["A8"] = "DATOS DEL MOVIMIENTO"
        ws["A8"].font = font_header
        ws["A8"].fill = fill_header
        ws["A8"].alignment = Alignment(horizontal="center")

        ws.merge_cells("F8:H8")
        ws["F8"] = "ENTRADAS"
        ws["F8"].font = font_header
        ws["F8"].fill = fill_header
        ws["F8"].alignment = Alignment(horizontal="center")

        ws.merge_cells("I8:K8")
        ws["I8"] = "SALIDAS (COGS FIFO)"
        ws["I8"].font = font_header
        ws["I8"].fill = fill_header
        ws["I8"].alignment = Alignment(horizontal="center")

        ws.merge_cells("L8:N8")
        ws["L8"] = "SALDO ACUMULADO"
        ws["L8"].font = font_header
        ws["L8"].fill = fill_header
        ws["L8"].alignment = Alignment(horizontal="center")

        ws.merge_cells("O8:P8")
        ws["O8"] = "TRAZABILIDAD"
        ws["O8"].font = font_header
        ws["O8"].fill = fill_header
        ws["O8"].alignment = Alignment(horizontal="center")

        subcols = [
            ("Fecha / Hora", Alignment(horizontal="center")),
            ("Documento", Alignment(horizontal="left")),
            ("Tipo", Alignment(horizontal="center")),
            ("Motivo", Alignment(horizontal="left")),
            ("Almacén", Alignment(horizontal="left")),
            ("Cantidad", Alignment(horizontal="right")),
            ("Costo Unit.", Alignment(horizontal="right")),
            ("Valor Total", Alignment(horizontal="right")),
            ("Cantidad", Alignment(horizontal="right")),
            ("Costo Unit.", Alignment(horizontal="right")),
            ("Valor Total", Alignment(horizontal="right")),
            ("Cantidad", Alignment(horizontal="right")),
            ("Costo Prom.", Alignment(horizontal="right")),
            ("Valor Total", Alignment(horizontal="right")),
            ("Capas FIFO", Alignment(horizontal="left")),
            ("Usuario / Ref.", Alignment(horizontal="left")),
        ]

        for idx, (label, align) in enumerate(subcols, start=1):
            cell = ws.cell(row=9, column=idx, value=label)
            cell.font = font_subhead
            cell.alignment = align
            if idx in (6, 7, 8):
                cell.fill = fill_subhead_in
            elif idx in (9, 10, 11):
                cell.fill = fill_subhead_out
            elif idx in (12, 13, 14):
                cell.fill = fill_subhead_bal
            else:
                cell.fill = PatternFill(start_color=C_HEADER_LIGHT, end_color=C_HEADER_LIGHT, fill_type="solid")
            cell.border = border_cell

        # 4. Fila de Saldo Inicial (Fila 10)
        curr_row = 10
        init_b = kardex["initialBalance"]
        ws.cell(row=curr_row, column=1, value=init_b.get("date") or "INICIO").font = font_data_bold
        ws.cell(row=curr_row, column=2, value="-").font = font_data
        ws.cell(row=curr_row, column=3, value="SALDO").font = font_data_bold
        ws.cell(row=curr_row, column=4, value="SALDO INICIAL ACUMULADO").font = font_data_bold
        ws.cell(row=curr_row, column=5, value=kardex.get("warehouseName")).font = font_data

        for c in range(6, 12):
            ws.cell(row=curr_row, column=c, value="-").alignment = Alignment(horizontal="center")

        c_iq = ws.cell(row=curr_row, column=12, value=init_b["quantity"])
        c_ic = ws.cell(row=curr_row, column=13, value=init_b["unitCost"])
        c_iv = ws.cell(row=curr_row, column=14, value=init_b["totalValue"])
        for c in (c_iq, c_ic, c_iv):
            c.font = font_data_bold

        ws.cell(row=curr_row, column=15, value="-").font = font_data
        ws.cell(row=curr_row, column=16, value="Apertura Período").font = font_data

        for col in range(1, 17):
            ws.cell(row=curr_row, column=col).border = border_cell

        # 5. Filas de Movimientos
        curr_row += 1
        for mov in kardex.get("movements", []):
            dt_display = mov.get("date", "")[:19].replace("T", " ")
            ws.cell(row=curr_row, column=1, value=dt_display).alignment = Alignment(horizontal="center")
            ws.cell(row=curr_row, column=2, value=mov.get("documentNumber") or mov.get("referenceId", "-"))
            ws.cell(row=curr_row, column=3, value=mov.get("type", "")).alignment = Alignment(horizontal="center")
            ws.cell(row=curr_row, column=4, value=mov.get("reason", ""))
            ws.cell(row=curr_row, column=5, value=mov.get("warehouseName", ""))

            # Entradas
            in_q = mov.get("inQty", 0.0)
            ws.cell(row=curr_row, column=6, value=in_q if in_q > 0 else 0)
            ws.cell(row=curr_row, column=7, value=mov.get("inUnitCost", 0.0) if in_q > 0 else 0)
            ws.cell(row=curr_row, column=8, value=mov.get("inTotalValue", 0.0) if in_q > 0 else 0)

            # Salidas
            out_q = mov.get("outQty", 0.0)
            ws.cell(row=curr_row, column=9, value=out_q if out_q > 0 else 0)
            ws.cell(row=curr_row, column=10, value=mov.get("outUnitCost", 0.0) if out_q > 0 else 0)
            ws.cell(row=curr_row, column=11, value=mov.get("outTotalValue", 0.0) if out_q > 0 else 0)

            # Saldos
            ws.cell(row=curr_row, column=12, value=mov.get("balanceQty", 0.0))
            ws.cell(row=curr_row, column=13, value=mov.get("balanceUnitCost", 0.0))
            ws.cell(row=curr_row, column=14, value=mov.get("balanceTotalValue", 0.0))

            layers_desc = ""
            if mov.get("costLayers"):
                layers_desc = ", ".join(f"{l['quantity']}u@RD${l['unitCost']}" for l in mov["costLayers"])
            ws.cell(row=curr_row, column=15, value=layers_desc)
            ws.cell(row=curr_row, column=16, value=mov.get("performedBy") or mov.get("notes", ""))

            for col_idx in range(1, 17):
                c = ws.cell(row=curr_row, column=col_idx)
                c.font = font_data
                c.border = border_cell
                if col_idx in (6, 9, 12):
                    c.number_format = "#,##0.00"
                    c.alignment = Alignment(horizontal="right")
                elif col_idx in (7, 8, 10, 11, 13, 14):
                    c.number_format = '"RD$ "#,##0.00'
                    c.alignment = Alignment(horizontal="right")

            curr_row += 1

        # 6. Fila de Totales del Período
        ws.cell(row=curr_row, column=4, value="TOTALES DEL PERÍODO:").font = font_data_bold
        ws.cell(row=curr_row, column=6, value=kardex["periodTotals"]["inQuantity"]).number_format = "#,##0.00"
        ws.cell(row=curr_row, column=8, value=kardex["periodTotals"]["inTotalValue"]).number_format = '"RD$ "#,##0.00'
        ws.cell(row=curr_row, column=9, value=kardex["periodTotals"]["outQuantity"]).number_format = "#,##0.00"
        ws.cell(row=curr_row, column=11, value=kardex["periodTotals"]["outTotalValue"]).number_format = '"RD$ "#,##0.00'
        ws.cell(row=curr_row, column=12, value=kardex["finalBalance"]["quantity"]).number_format = "#,##0.00"
        ws.cell(row=curr_row, column=14, value=kardex["finalBalance"]["totalValue"]).number_format = '"RD$ "#,##0.00'

        for col_idx in range(1, 17):
            c = ws.cell(row=curr_row, column=col_idx)
            c.font = font_data_bold
            c.border = border_top_thick

        # 7. Conciliación y Auditoría en el pie de página
        reconcil = kardex.get("reconciliation", {})
        curr_row += 2
        ws.cell(row=curr_row, column=1, value="CONCILIACIÓN Y AUDITORÍA DE INVENTARIO:").font = font_section
        curr_row += 1
        ws.cell(row=curr_row, column=1, value=f"• Existencia Física en Almacén (inventory_stock): {reconcil.get('stockQty', 0):,.2f} uds").font = font_data
        ws.cell(row=curr_row, column=6, value=f"• Saldo Cantidad en Kardex: {kardex['finalBalance']['quantity']:,.2f} uds").font = font_data
        ws.cell(row=curr_row, column=10, value=f"• Diferencia Cantidad: {reconcil.get('qtyDifference', 0):,.2f} uds").font = font_data_bold
        curr_row += 1
        ws.cell(row=curr_row, column=1, value=f"• Valorización Capas Activas (inventory_cost_ledger): RD$ {reconcil.get('ledgerValue', 0):,.2f}").font = font_data
        ws.cell(row=curr_row, column=6, value=f"• Saldo Valor en Kardex: RD$ {kardex['finalBalance']['totalValue']:,.2f}").font = font_data
        ws.cell(row=curr_row, column=10, value=f"• Diferencia Valor: RD$ {reconcil.get('valueDifference', 0):,.2f}").font = font_data_bold
        curr_row += 1
        ws.cell(row=curr_row, column=1, value=f"• Estado de Conciliación: {reconcil.get('status', 'OK')}").font = font_data_bold

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 11)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    # ── 4. EXPORTACIÓN PDF (WEASYPRINT) ─────────────────────────────────────

    @classmethod
    def export_kardex_pdf(
        cls,
        company_id: str,
        item_id: str,
        warehouse_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> bytes:
        """Genera un archivo PDF con formato corporativo utilizando WeasyPrint."""
        from flask import render_template
        from app.utils.pdf import pdf_write_options

        kardex = cls.get_kardex_summary(
            company_id=company_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            date_from=date_from,
            date_to=date_to,
            sandbox=sandbox,
            owner_uid=owner_uid
        )

        company_profile = DatabaseService.get_company_profile(owner_uid=owner_uid or "", company_id=company_id) or {}
        rendered_html = render_template(
            "inventario/kardex_pdf.html",
            kardex=kardex,
            company=company_profile,
            now=datetime.now(timezone.utc)
        )

        try:
            from weasyprint import HTML as WeasyprintHTML
            return WeasyprintHTML(string=rendered_html, base_url=base_url).write_pdf(**pdf_write_options())
        except Exception as e:
            print(f"⚠️ WeasyPrint no disponible o error al generar PDF de Kardex: {e}")
            fallback_pdf = (
                b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
                b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
                b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n"
                b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
                b"5 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 50 700 Td (Kardex Valorizado) Tj ET\nendstream\nendobj\n"
                b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
                b"0000000244 00000 n \n0000000325 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n419\n%%EOF\n"
            )
            return fallback_pdf

    # ── 5. MÉTODOS AUXILIARES Y NORMALIZACIÓN ───────────────────────────────

    @classmethod
    def _fetch_item_transactions(cls, company_id: str, item_id: str, sandbox: bool = True, owner_uid: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recupera todas las transacciones históricas del artículo desde Firestore."""
        txs = []
        if not firebase_initialized:
            return txs
        coll_name = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
        try:
            coll = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name)
            docs = coll.stream() if hasattr(coll, "stream") else coll.get()
            for doc in docs:
                data = doc.to_dict() or {}
                if data.get("itemId") == item_id:
                    data["id"] = doc.id
                    txs.append(data)
        except Exception as e:
            print(f"⚠️ Error al leer transacciones de inventario para Kardex: {e}")
        return txs

    @classmethod
    def _project_transaction_rows(cls, tx: Dict[str, Any], warehouse_id: Optional[str] = None, wh_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        wh_map = wh_map or {}
        tx_type = tx.get("type", "ENTRADA")
        qty = float(tx.get("quantity", 0.0))
        unit_cost = float(tx.get("unitCost", 0.0))
        total_val = float(tx.get("totalValue", round(qty * unit_cost, 2)))
        orig_wh = tx.get("originWarehouseId", "")
        dest_wh = tx.get("destinationWarehouseId", "")
        cost_layers = tx.get("costLayers", [])
        tx_id = tx.get("id", "")
        date_iso = tx.get("date") or tx.get("createdAt") or ""
        doc_num = tx.get("referenceId") or tx.get("idempotencyKey") or tx_id[:8]
        reason = tx.get("reason") or tx_type
        notes = tx.get("notes", "")
        performed_by = tx.get("performedBy", "Sistema")

        rows = []

        if tx_type == "ENTRADA":
            if not warehouse_id or dest_wh == warehouse_id:
                rows.append({
                    "transactionId": tx_id,
                    "date": date_iso,
                    "createdAt": tx.get("createdAt") or date_iso,
                    "type": "ENTRADA",
                    "reason": reason,
                    "documentNumber": doc_num,
                    "referenceType": tx.get("referenceType", "ENTRADA"),
                    "referenceId": tx.get("referenceId", ""),
                    "warehouseId": dest_wh,
                    "warehouseName": wh_map.get(dest_wh, dest_wh),
                    "inQty": qty,
                    "inUnitCost": unit_cost,
                    "inTotalValue": total_val,
                    "outQty": 0.0,
                    "outUnitCost": 0.0,
                    "outTotalValue": 0.0,
                    "costLayers": cost_layers,
                    "performedBy": performed_by,
                    "notes": notes,
                })

        elif tx_type == "SALIDA":
            if not warehouse_id or orig_wh == warehouse_id:
                rows.append({
                    "transactionId": tx_id,
                    "date": date_iso,
                    "createdAt": tx.get("createdAt") or date_iso,
                    "type": "SALIDA",
                    "reason": reason,
                    "documentNumber": doc_num,
                    "referenceType": tx.get("referenceType", "SALIDA"),
                    "referenceId": tx.get("referenceId", ""),
                    "warehouseId": orig_wh,
                    "warehouseName": wh_map.get(orig_wh, orig_wh),
                    "inQty": 0.0,
                    "inUnitCost": 0.0,
                    "inTotalValue": 0.0,
                    "outQty": qty,
                    "outUnitCost": unit_cost,
                    "outTotalValue": total_val,
                    "costLayers": cost_layers,
                    "performedBy": performed_by,
                    "notes": notes,
                })

        elif tx_type == "TRANSFERENCIA":
            if warehouse_id:
                if orig_wh == warehouse_id:
                    rows.append({
                        "transactionId": tx_id,
                        "date": date_iso,
                        "createdAt": tx.get("createdAt") or date_iso,
                        "type": "TRANSFERENCIA",
                        "reason": f"TRANSF. SALIDA HACIA {wh_map.get(dest_wh, dest_wh)}",
                        "documentNumber": doc_num,
                        "referenceType": "TRANSFER_OUT",
                        "referenceId": tx.get("referenceId", ""),
                        "warehouseId": orig_wh,
                        "warehouseName": wh_map.get(orig_wh, orig_wh),
                        "inQty": 0.0,
                        "inUnitCost": 0.0,
                        "inTotalValue": 0.0,
                        "outQty": qty,
                        "outUnitCost": unit_cost,
                        "outTotalValue": total_val,
                        "costLayers": cost_layers,
                        "performedBy": performed_by,
                        "notes": notes,
                    })
                elif dest_wh == warehouse_id:
                    rows.append({
                        "transactionId": tx_id,
                        "date": date_iso,
                        "createdAt": tx.get("createdAt") or date_iso,
                        "type": "TRANSFERENCIA",
                        "reason": f"TRANSF. ENTRADA DESDE {wh_map.get(orig_wh, orig_wh)}",
                        "documentNumber": doc_num,
                        "referenceType": "TRANSFER_IN",
                        "referenceId": tx.get("referenceId", ""),
                        "warehouseId": dest_wh,
                        "warehouseName": wh_map.get(dest_wh, dest_wh),
                        "inQty": qty,
                        "inUnitCost": unit_cost,
                        "inTotalValue": total_val,
                        "outQty": 0.0,
                        "outUnitCost": 0.0,
                        "outTotalValue": 0.0,
                        "costLayers": cost_layers,
                        "performedBy": performed_by,
                        "notes": notes,
                    })
            else:
                rows.append({
                    "transactionId": tx_id,
                    "date": date_iso,
                    "createdAt": tx.get("createdAt") or date_iso,
                    "type": "TRANSFERENCIA",
                    "reason": f"TRANSF: {wh_map.get(orig_wh, orig_wh)} ➔ {wh_map.get(dest_wh, dest_wh)}",
                    "documentNumber": doc_num,
                    "referenceType": "TRANSFER_INTERNAL",
                    "referenceId": tx.get("referenceId", ""),
                    "warehouseId": f"{orig_wh}➔{dest_wh}",
                    "warehouseName": f"{wh_map.get(orig_wh, orig_wh)} ➔ {wh_map.get(dest_wh, dest_wh)}",
                    "inQty": qty,
                    "inUnitCost": unit_cost,
                    "inTotalValue": total_val,
                    "outQty": qty,
                    "outUnitCost": unit_cost,
                    "outTotalValue": total_val,
                    "costLayers": cost_layers,
                    "performedBy": performed_by,
                    "notes": notes,
                })

        elif tx_type == "AJUSTE":
            adj_wh = dest_wh or orig_wh
            if not warehouse_id or adj_wh == warehouse_id:
                if qty >= 0:
                    rows.append({
                        "transactionId": tx_id,
                        "date": date_iso,
                        "createdAt": tx.get("createdAt") or date_iso,
                        "type": "AJUSTE",
                        "reason": reason,
                        "documentNumber": doc_num,
                        "referenceType": tx.get("referenceType", "AJUSTE"),
                        "referenceId": tx.get("referenceId", ""),
                        "warehouseId": adj_wh,
                        "warehouseName": wh_map.get(adj_wh, adj_wh),
                        "inQty": qty,
                        "inUnitCost": unit_cost,
                        "inTotalValue": total_val,
                        "outQty": 0.0,
                        "outUnitCost": 0.0,
                        "outTotalValue": 0.0,
                        "costLayers": cost_layers,
                        "performedBy": performed_by,
                        "notes": notes,
                    })
                else:
                    pos_q = abs(qty)
                    rows.append({
                        "transactionId": tx_id,
                        "date": date_iso,
                        "createdAt": tx.get("createdAt") or date_iso,
                        "type": "AJUSTE",
                        "reason": reason,
                        "documentNumber": doc_num,
                        "referenceType": tx.get("referenceType", "AJUSTE"),
                        "referenceId": tx.get("referenceId", ""),
                        "warehouseId": adj_wh,
                        "warehouseName": wh_map.get(adj_wh, adj_wh),
                        "inQty": 0.0,
                        "inUnitCost": 0.0,
                        "inTotalValue": 0.0,
                        "outQty": pos_q,
                        "outUnitCost": unit_cost,
                        "outTotalValue": total_val,
                        "costLayers": cost_layers,
                        "performedBy": performed_by,
                        "notes": notes,
                    })

        return rows

    @classmethod
    def _sort_key(cls, row: Dict[str, Any]) -> Tuple[str, str, int, str]:
        d = str(row.get("date") or "")
        c = str(row.get("createdAt") or "")
        p = cls.TYPE_SORT_PRIORITY.get(row.get("type", ""), 99)
        t_id = str(row.get("transactionId") or "")
        return (d, c, p, t_id)

    @classmethod
    def _reconcile_item(
        cls,
        company_id: str,
        item_id: str,
        kardex_data: Dict[str, Any],
        warehouse_id: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Realiza la conciliación estricta del saldo del Kardex contra:
        1. inventory_stock (existencia física por almacén)
        2. inventory_cost_ledger (suma de balanceQty * unitCost en capas activas)
        3. items.totalStock (vista materializada de catálogo)
        """
        kardex_final_qty = float(kardex_data["finalBalance"]["quantity"])
        kardex_final_val = float(kardex_data["finalBalance"]["totalValue"])

        # 1. Leer existencias físicas desde inventory_stock
        stock_coll_name = "sandbox_inventory_stock" if sandbox else "inventory_stock"
        stock_coll = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=stock_coll_name)

        physical_stock_qty = 0.0
        try:
            if warehouse_id:
                doc = stock_coll.document(f"{item_id}_{warehouse_id}").get()
                if doc.exists:
                    physical_stock_qty = float(doc.to_dict().get("quantity", 0.0))
            else:
                docs = stock_coll.stream() if hasattr(stock_coll, "stream") else stock_coll.get()
                for d in docs:
                    d_data = d.to_dict() or {}
                    if d_data.get("itemId") == item_id:
                        physical_stock_qty += float(d_data.get("quantity", 0.0))
        except Exception as e:
            print(f"⚠️ Error al leer inventory_stock para conciliación: {e}")

        # 2. Leer valorización de capas activas desde inventory_cost_ledger
        ledger_coll_name = "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger"
        ledger_coll = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=ledger_coll_name)

        ledger_val = 0.0
        ledger_qty = 0.0
        try:
            docs = ledger_coll.stream() if hasattr(ledger_coll, "stream") else ledger_coll.get()
            for d in docs:
                d_data = d.to_dict() or {}
                if d_data.get("itemId") != item_id:
                    continue
                if warehouse_id and d_data.get("warehouseId") != warehouse_id:
                    continue
                bal_q = float(d_data.get("balanceQty", 0.0))
                u_cost = float(d_data.get("unitCost", 0.0))
                if bal_q > 0:
                    ledger_qty += bal_q
                    ledger_val += (bal_q * u_cost)
        except Exception as e:
            print(f"⚠️ Error al leer inventory_cost_ledger para conciliación: {e}")

        # 3. Leer totalStock del catálogo
        catalog_stock = float(kardex_data.get("item", {}).get("totalStock", 0.0))

        qty_diff = round(kardex_final_qty - physical_stock_qty, 4)
        val_diff = round(kardex_final_val - ledger_val, 2)
        catalog_diff = round(catalog_stock - physical_stock_qty, 4) if not warehouse_id else 0.0

        is_qty_ok = abs(qty_diff) <= 0.0001
        is_val_ok = abs(val_diff) <= 0.05
        is_catalog_ok = abs(catalog_diff) <= 0.0001

        status = "OK"
        notes = []
        if not is_qty_ok:
            status = "DISCREPANCY"
            notes.append(f"Diferencia de cantidad: Kardex ({kardex_final_qty}) vs Stock Físico ({physical_stock_qty})")
        if not is_val_ok:
            status = "DISCREPANCY"
            notes.append(f"Diferencia de valor: Kardex (RD${kardex_final_val:,.2f}) vs Capas FIFO (RD${ledger_val:,.2f})")
        if not is_catalog_ok and not warehouse_id:
            status = "WARNING" if status == "OK" else "DISCREPANCY"
            notes.append(f"Catálogo totalStock ({catalog_stock}) difiere de suma de almacenes ({physical_stock_qty})")

        return {
            "stockQty": round(physical_stock_qty, 4),
            "kardexQty": round(kardex_final_qty, 4),
            "qtyDifference": qty_diff,
            "ledgerValue": round(ledger_val, 2),
            "kardexValue": round(kardex_final_val, 2),
            "valueDifference": val_diff,
            "catalogTotalStock": catalog_stock,
            "catalogDifference": catalog_diff,
            "status": status,
            "notes": "; ".join(notes) if notes else "Saldos conciliados correctamente."
        }

    @classmethod
    def _get_item_info(cls, company_id: str, item_id: str, sandbox: bool = True, owner_uid: Optional[str] = None) -> Dict[str, Any]:
        """Obtiene la información básica de un artículo."""
        coll_name = "sandbox_items" if sandbox else "items"
        try:
            doc = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name).document(item_id).get()
            if doc.exists:
                res = doc.to_dict() or {}
                res["id"] = doc.id
                return res
        except Exception as e:
            print(f"⚠️ Error al leer item '{item_id}' para Kardex: {e}")
        return {"id": item_id, "name": "Artículo", "code": "", "costPrice": 0.0, "totalStock": 0.0}

    @classmethod
    def _get_all_company_items(cls, company_id: str, sandbox: bool = True, owner_uid: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recupera el listado completo de artículos de la empresa."""
        coll_name = "sandbox_items" if sandbox else "items"
        items = []
        try:
            docs = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name).stream()
            for d in docs:
                data = d.to_dict() or {}
                data["id"] = d.id
                items.append(data)
        except Exception as e:
            print(f"⚠️ Error al leer items para resumen de Kardex: {e}")
        return items

    @classmethod
    def _empty_kardex_response(cls, company_id: str, item_id: str, warehouse_id: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> Dict[str, Any]:
        """Retorna una respuesta vacía estructurada."""
        return {
            "companyId": company_id or "",
            "itemId": item_id or "",
            "item": {},
            "warehouseId": warehouse_id,
            "warehouseName": "Todos los Almacenes",
            "dateFrom": date_from,
            "dateTo": date_to,
            "initialBalance": {"quantity": 0.0, "totalValue": 0.0, "unitCost": 0.0, "date": date_from or ""},
            "movements": [],
            "finalBalance": {"quantity": 0.0, "totalValue": 0.0, "unitCost": 0.0},
            "periodTotals": {"inQuantity": 0.0, "inTotalValue": 0.0, "outQuantity": 0.0, "outTotalValue": 0.0},
            "reconciliation": {
                "stockQty": 0.0,
                "kardexQty": 0.0,
                "qtyDifference": 0.0,
                "ledgerValue": 0.0,
                "kardexValue": 0.0,
                "valueDifference": 0.0,
                "status": "OK",
                "notes": "Sin movimientos registrados."
            }
        }
