"""DGTExportService — Exportación de formularios DGT en .txt (SIRLA), .xlsx y .pdf.

Formato principal: .txt tab-delimited, UTF-8 sin BOM, 22 columnas, sin cabecera.
Formatos secundarios: .xlsx (revisión) y .pdf (visualización/impresión).
"""

import csv
import io
from datetime import datetime


def _format_date(d: str) -> str:
    """Retorna la fecha tal cual (ya debe venir en DD/MM/AAAA)."""
    return d


class DGTExportService:

    @staticmethod
    def to_txt(lines: list[dict]) -> str:
        """Genera archivo .txt tab-delimited para SIRLA (22 columnas, sin cabecera)."""
        output = io.StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE)

        for emp in lines:
            writer.writerow([
                emp.get("tipoDocumento", 1),
                emp.get("documento", ""),
                emp.get("nombres", "")[:40],
                emp.get("apellidos", "")[:40],
                emp.get("nacionalidad", 1),
                emp.get("sexo", ""),
                _format_date(emp.get("fechaNacimiento", "")),
                emp.get("estadoCivil", ""),
                f"{float(emp.get('salario', 0)):.2f}",
                emp.get("tipoMoneda", 1),
                emp.get("frecuenciaPago", 1),
                emp.get("ocupacionCodigo", ""),
                emp.get("ocupacionTexto", ""),
                _format_date(emp.get("fechaIngreso", "")),
                emp.get("tipoContrato", 1),
                str(emp.get("horasSemanales", 44)),
                str(emp.get("turnoTrabajo", 1)),
                str(emp.get("estadoTrabajador", 1)),
                str(emp.get("tipoNovedad", 0)),
                _format_date(emp.get("fechaNovedad", "")),
                str(emp.get("gradoInstruccion", 0)),
                str(emp.get("concesionVacaciones", 1)),
            ])

        return output.getvalue()

    @staticmethod
    def to_excel(lines: list[dict], title: str = "DGT") -> io.BytesIO:
        """Genera archivo .xlsx para revisión (con cabecera y estilos)."""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = title[:31]

        headers = [
            "Tipo Doc", "Documento", "Nombres", "Apellidos", "Nacionalidad",
            "Sexo", "Fecha Nac.", "Estado Civil", "Salario", "Moneda",
            "Frec. Pago", "Cód. Ocup.", "Ocupación", "Fecha Ingreso",
            "Tipo Contrato", "Horas Sem.", "Turno", "Estado",
            "Tipo Novedad", "Fecha Novedad", "Instrucción", "Vacaciones",
        ]

        # Header style
        h_font = Font(bold=True, size=10, color="FFFFFF")
        h_fill = PatternFill(start_color="2D3748", end_color="2D3748", fill_type="solid")
        h_align = Alignment(horizontal="center", vertical="center")
        thin_border = Border(
            bottom=Side(style="hair", color="E2E8F0"),
        )

        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = h_font
            cell.fill = h_fill
            cell.alignment = h_align

        for row_idx, emp in enumerate(lines, 2):
            data = [
                emp.get("tipoDocumento", 1),
                emp.get("documento", ""),
                emp.get("nombres", ""),
                emp.get("apellidos", ""),
                emp.get("nacionalidad", 1),
                emp.get("sexo", ""),
                _format_date(emp.get("fechaNacimiento", "")),
                emp.get("estadoCivil", ""),
                float(emp.get("salario", 0)),
                emp.get("tipoMoneda", 1),
                emp.get("frecuenciaPago", 1),
                emp.get("ocupacionCodigo", ""),
                emp.get("ocupacionTexto", ""),
                _format_date(emp.get("fechaIngreso", "")),
                emp.get("tipoContrato", 1),
                emp.get("horasSemanales", 44),
                emp.get("turnoTrabajo", 1),
                emp.get("estadoTrabajador", 1),
                emp.get("tipoNovedad", 0),
                _format_date(emp.get("fechaNovedad", "")),
                emp.get("gradoInstruccion", 0),
                emp.get("concesionVacaciones", 1),
            ]
            for col_idx, val in enumerate(data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = Font(size=9)
                cell.border = thin_border
                if isinstance(val, float):
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif col_idx == 2:
                    cell.number_format = "@"
                    cell.alignment = Alignment(horizontal="center")

        # Auto-width
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    val_len = len(str(cell.value))
                    max_len = max(max_len, val_len)
            ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 50)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def to_pdf(lines: list[dict], form_type: str, title: str,
               owner_info: dict = None) -> io.BytesIO:
        """Genera PDF usando WeasyPrint (debe existir el template)."""
        from flask import render_template
        import weasyprint

        html = render_template(
            f"rrhh/dgt/{form_type}_pdf.html",
            lines=lines,
            title=title,
            owner_info=owner_info or {},
            now=datetime.now(),
        )
        pdf = weasyprint.HTML(string=html).write_pdf()
        output = io.BytesIO(pdf)
        output.seek(0)
        return output
