"""Exportadores de consulta para declaraciones IR-17."""

import csv
import io

from app.services.ir17_calculator import calculate_ir17


class IR17ExportService:
    @staticmethod
    def csv(data):
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["RNC", "Periodo", "TipoDeclaracion", "Casilla", "Concepto", "Base", "Tasa", "Impuesto", "Fuente", "Estado"])
        for item in data.get("line_items", []):
            writer.writerow([
                data.get("rnc", ""), data.get("period", ""), data.get("declaration_type", ""),
                item.get("number", ""), item.get("concept", ""), item.get("base", "0.00"),
                item.get("rate", "0"), item.get("tax", "0.00"), item.get("source", "manual"),
                data.get("status", "Borrador"),
            ])
        return out.getvalue().encode("utf-8-sig")

    @staticmethod
    def xlsx(data):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = Workbook()
        ws = wb.active
        ws.title = "IR-17"
        ws.append(["DECLARACIÓN JURADA O PAGO DE OTRAS RETENCIONES Y RETRIBUCIONES COMPLEMENTARIAS"])
        ws.append(["RNC", data.get("rnc", ""), "Razón social", data.get("razon_social", ""), "Período", data.get("period", "")])
        ws.append([])
        headers = ["Casilla", "Concepto", "Base imponible", "Tasa", "Impuesto", "Fuente"]
        ws.append(headers)
        for cell in ws[4]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0F766E")
            cell.alignment = Alignment(wrap_text=True)
        for item in data.get("line_items", []):
            ws.append([item.get("number"), item.get("concept"), float(item.get("base", 0)), float(item.get("rate", 0)), float(item.get("tax", 0)), item.get("source", "manual")])
        calc = calculate_ir17(data)
        ws.append([])
        for label, key in (("Total otras retenciones", "total_other_withholdings"), ("Convenios", "conventions_amount"), ("Retribuciones complementarias", "supplementary_tax"), ("Impuesto a pagar", "tax_due"), ("Diferencia a pagar", "difference_to_pay"), ("Nuevo saldo a favor", "new_balance_favor"), ("Recargos", "surcharges"), ("Interés indemnizatorio", "indemnity_interest"), ("Total a pagar", "total_payable")):
            ws.append([label, float(calc[key])])
        for column, width in {"A": 12, "B": 80, "C": 18, "D": 12, "E": 18, "F": 16}.items():
            ws.column_dimensions[column].width = width
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return out

    @staticmethod
    def pdf_html(data):
        calc = calculate_ir17(data)
        rows = "".join(
            f"<tr><td>{item.get('number')}</td><td>{item.get('concept')}</td><td>{item.get('base', '0.00')}</td><td>{item.get('rate')}</td><td>{item.get('tax', '0.00')}</td></tr>"
            for item in data.get("line_items", [])
        )
        return f"""<!doctype html><html><head><meta charset='utf-8'><style>
        @page {{ size: letter; margin: 12mm; }} body {{ font-family: Arial, sans-serif; font-size: 9px; color:#1f2937; }}
        h1 {{ font-size: 16px; text-align:center; }} h2 {{ font-size: 11px; background:#0f766e; color:#fff; padding:5px; }}
        table {{ width:100%; border-collapse:collapse; margin-bottom:10px; }} th,td {{ border:1px solid #cbd5e1; padding:4px; }} th {{ background:#e2e8f0; }}
        .summary {{ width:45%; margin-left:auto; }} .muted {{ color:#64748b; }}
        </style></head><body><h1>IR-17 - Declaración Jurada o Pago de Otras Retenciones</h1>
        <p><b>RNC/Cédula:</b> {data.get('rnc','')} &nbsp; <b>Razón social:</b> {data.get('razon_social','')}<br>
        <b>Período:</b> {data.get('period','')} &nbsp; <b>Tipo:</b> {data.get('declaration_type','Normal')}<br>
        <span class='muted'>Versión fiscal: {data.get('rules_version','2026')} | Documento generado por VykOne para revisión</span></p>
        <h2>Otras retenciones</h2><table><thead><tr><th>Casilla</th><th>Concepto</th><th>Base</th><th>Tasa</th><th>Impuesto</th></tr></thead><tbody>{rows}</tbody></table>
        <h2>Liquidación</h2><table class='summary'>
        <tr><td>Total otras retenciones</td><td>{calc['total_other_withholdings']}</td></tr><tr><td>Convenios</td><td>{calc['conventions_amount']}</td></tr>
        <tr><td>Retribuciones complementarias</td><td>{calc['supplementary_tax']}</td></tr><tr><td>Impuesto a pagar</td><td>{calc['tax_due']}</td></tr>
        <tr><td>Diferencia a pagar</td><td>{calc['difference_to_pay']}</td></tr><tr><td>Nuevo saldo a favor</td><td>{calc['new_balance_favor']}</td></tr>
        <tr><td>Recargos</td><td>{calc['surcharges']}</td></tr><tr><td>Interés indemnizatorio</td><td>{calc['indemnity_interest']}</td></tr>
        <tr><th>Total a pagar</th><th>{calc['total_payable']}</th></tr></table>
        <h2>Datos de presentación DGII</h2><p>Autorización: {data.get('authorization_number','')} &nbsp; Acuse: {data.get('acknowledgement_number','')} &nbsp; Fecha: {data.get('dgii_filing_date','')}</p>
        </body></html>"""
