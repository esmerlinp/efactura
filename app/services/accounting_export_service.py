import csv
import io
from datetime import datetime
from decimal import Decimal

from app.services.db_service import DatabaseService


EXPORT_FORMATS = {
    "csv_std": "CSV Estándar (Excel)",
    "quickbooks": "QuickBooks (IIF/QBO)",
    "sage50": "Sage 50 (Pez)",
    "odoo": "Odoo",
    "softland": "Softland",
}

DEFAULT_CHART_OF_ACCOUNTS = {
    "CXC": "1.1.3.01",          # Cuentas por Cobrar Clientes (Débito)
    "VENTAS": "4.1.1.01",       # Ingresos por Ventas (Crédito)
    "ITBIS_POR_PAGAR": "2.1.1.02",  # ITBIS por Pagar (Crédito)
    "ITBIS_RETENIDO": "2.1.1.03",   # ITBIS Retenido
    "ISR_RETENIDO": "2.1.1.04",     # ISR Retenido
    "CXP": "2.1.2.01",          # Cuentas por Pagar Proveedores (Crédito)
    "COMPRAS": "6.1.1.01",      # Compras / Costos (Débito)
    "GASTOS": "5.1.1.01",       # Gastos Operativos (Débito)
    "ITBIS_CREDITO": "1.1.4.01", # ITBIS por Recuperar (Débito)
}


class AccountingExportService:

    @classmethod
    def _get_chart_of_accounts(cls, owner_uid):
        profile = DatabaseService.get_company_profile(owner_uid)
        saved = profile.get("chartOfAccounts", {}) if profile else {}
        return {**DEFAULT_CHART_OF_ACCOUNTS, **saved}

    @classmethod
    def _format_date(cls, d):
        if not d:
            return ""
        return str(d)[:10]

    @classmethod
    def _sanitize(cls, val):
        if val is None:
            return ""
        return str(val).strip()

    @classmethod
    def export_sales(cls, owner_uid, invoices, fmt="csv_std"):
        """Export invoices as accounting entries in the given format."""
        coa = cls._get_chart_of_accounts(owner_uid)
        entries = []
        for inv in invoices:
            total = float(inv.get("netPayable", inv.get("total", 0)))
            subtotal = float(inv.get("subtotal", 0))
            itbis = float(inv.get("totalITBIS", inv.get("itbis", 0)))
            retained_isr = float(inv.get("retainedISR", 0))
            retained_itbis = float(inv.get("retainedITBIS", 0))
            date = cls._format_date(inv.get("date", ""))
            ncf = inv.get("encf", inv.get("ncf", ""))
            client = inv.get("clientName", inv.get("razonSocial", "Consumidor Final"))
            rnc = inv.get("clientRNC", "")
            inv_num = inv.get("invoiceNumber", inv.get("number", ""))

            entries.append({
                "date": date,
                "reference": inv_num,
                "ncf": ncf,
                "client": client,
                "rnc": rnc,
                "subtotal": subtotal,
                "itbis": itbis,
                "total": total,
                "retained_isr": retained_isr,
                "retained_itbis": retained_itbis,
                "account_debit_cxc": coa["CXC"],
                "account_credit_sales": coa["VENTAS"],
                "account_credit_itbis": coa["ITBIS_POR_PAGAR"],
                "account_retained_itbis": coa["ITBIS_RETENIDO"],
                "account_retained_isr": coa["ISR_RETENIDO"],
            })

        export_fns = {
            "csv_std": cls._export_csv_std,
            "quickbooks": cls._export_quickbooks,
            "sage50": cls._export_sage50,
            "odoo": cls._export_odoo,
            "softland": cls._export_softland,
        }
        fn = export_fns.get(fmt, cls._export_csv_std)
        return fn(entries)

    @classmethod
    def export_expenses(cls, owner_uid, expenses, fmt="csv_std"):
        """Export expenses as accounting entries."""
        coa = cls._get_chart_of_accounts(owner_uid)
        entries = []
        for exp in expenses:
            total_amount = float(exp.get("amount", exp.get("total", 0)))
            itbis = float(exp.get("itbisAmount", exp.get("itbis", 0)))
            net_amount = max(0.0, total_amount - itbis)
            date = cls._format_date(exp.get("date", ""))
            supplier = exp.get("supplierName", exp.get("providerName", "—"))
            rnc = exp.get("supplierRnc", exp.get("rncEmisor", ""))
            concept = exp.get("concept", exp.get("description", "Gasto"))
            ncf = exp.get("ncf", "")

            entries.append({
                "date": date,
                "reference": exp.get("id", "")[:8],
                "ncf": ncf,
                "supplier": supplier,
                "rnc": rnc,
                "concept": concept,
                "amount": net_amount,
                "itbis": itbis,
                "total": total_amount,
                "account_debit": coa["GASTOS"],
                "account_itbis": coa["ITBIS_CREDITO"],
                "account_credit_cxp": coa["CXP"],
            })

        export_fns = {
            "csv_std": cls._export_expenses_csv_std,
            "quickbooks": cls._export_expenses_quickbooks,
            "sage50": cls._export_expenses_sage50,
            "odoo": cls._export_expenses_odoo,
            "softland": cls._export_expenses_softland,
        }
        fn = export_fns.get(fmt, cls._export_expenses_csv_std)
        return fn(entries)

    @classmethod
    def _export_csv_std(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Fecha", "Referencia", "NCF", "Cliente", "RNC",
                         "Subtotal", "ITBIS", "Total", "Ret. ISR", "Ret. ITBIS",
                         "Cuenta Débito", "Monto Débito", "Cuenta Crédito", "Monto Crédito"])
        for e in entries:
            writer.writerow([
                e["date"], e["reference"], e["ncf"],
                e["client"], e["rnc"],
                f"{e['subtotal']:.2f}", f"{e['itbis']:.2f}", f"{e['total']:.2f}",
                f"{e['retained_isr']:.2f}", f"{e['retained_itbis']:.2f}",
                e["account_debit_cxc"], f"{e['total']:.2f}",
                e["account_credit_sales"], f"{e['subtotal']:.2f}",
            ])
            if e["itbis"] > 0:
                writer.writerow([
                    e["date"], e["reference"], e["ncf"],
                    "", "", "", "", "", "", "",
                    "", "",
                    e["account_credit_itbis"], f"{e['itbis']:.2f}",
                ])
            if e["retained_isr"] > 0:
                writer.writerow([
                    e["date"], e["reference"], e["ncf"],
                    "", "", "", "", "", "", "",
                    e["account_retained_isr"], f"{e['retained_isr']:.2f}",
                    "", "",
                ])
            if e["retained_itbis"] > 0:
                writer.writerow([
                    e["date"], e["reference"], e["ncf"],
                    "", "", "", "", "", "", "",
                    e["account_retained_itbis"], f"{e['retained_itbis']:.2f}",
                    "", "",
                ])
        return cls._bom_output(output)

    @classmethod
    def _export_quickbooks(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["!TRNS", "TRNSID", "TRNSTYPE", "DATE", "ACCNT", "AMOUNT", "DOCNUM", "MEMO"])
        writer.writerow(["!SPL", "SPLID", "TRNSTYPE", "DATE", "ACCNT", "AMOUNT", "DOCNUM", "MEMO"])
        for e in entries:
            writer.writerow(["TRNS", e["reference"], "INVOICE", e["date"],
                             e["account_debit_cxc"], f"{e['total']:.2f}",
                             e["ncf"], f"Factura {e['reference']} - {e['client']}"])
            writer.writerow(["SPL", "", "INVOICE", e["date"],
                             e["account_credit_sales"], f"{-e['subtotal']:.2f}",
                             e["ncf"], ""])
            if e["itbis"] > 0:
                writer.writerow(["SPL", "", "INVOICE", e["date"],
                                 e["account_credit_itbis"], f"{-e['itbis']:.2f}",
                                 e["ncf"], ""])
            if e["retained_isr"] > 0:
                writer.writerow(["SPL", "", "INVOICE", e["date"],
                                 e["account_retained_isr"], f"{e['retained_isr']:.2f}",
                                 e["ncf"], ""])
            if e["retained_itbis"] > 0:
                writer.writerow(["SPL", "", "INVOICE", e["date"],
                                 e["account_retained_itbis"], f"{e['retained_itbis']:.2f}",
                                 e["ncf"], ""])
        return cls._bom_output(output)

    @classmethod
    def _export_sage50(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["ACCTNO", "DATE", "TRNSID", "AMOUNT", "TYPE", "MEMO", "CLEAR"])
        for e in entries:
            writer.writerow([e["account_debit_cxc"], e["date"], e["reference"],
                             f"{e['total']:.2f}", "INV", f"Factura {e['reference']}", "N"])
            writer.writerow([e["account_credit_sales"], e["date"], e["reference"],
                             f"{-e['subtotal']:.2f}", "INV", "", "N"])
            if e["itbis"] > 0:
                writer.writerow([e["account_credit_itbis"], e["date"], e["reference"],
                                 f"{-e['itbis']:.2f}", "INV", "", "N"])
        return cls._bom_output(output)

    @classmethod
    def _export_odoo(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["account_id", "partner_id", "date", "ref", "debit", "credit"])
        for e in entries:
            writer.writerow([e["account_debit_cxc"], e["client"], e["date"],
                             e["reference"], f"{e['total']:.2f}", "0.00"])
            writer.writerow([e["account_credit_sales"], e["client"], e["date"],
                             e["reference"], "0.00", f"{e['subtotal']:.2f}"])
            if e["itbis"] > 0:
                writer.writerow([e["account_credit_itbis"], e["client"], e["date"],
                                 e["reference"], "0.00", f"{e['itbis']:.2f}"])
        return cls._bom_output(output)

    @classmethod
    def _export_softland(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["TIPO", "FECHA", "COMPROBANTE", "CUENTA", "DEBE", "HABER", "DETALLE"])
        for e in entries:
            writer.writerow(["FC", e["date"], e["reference"],
                             e["account_debit_cxc"], f"{e['total']:.2f}", "0.00",
                             f"Factura {e['reference']} - {e['client']}"])
            writer.writerow(["FC", e["date"], e["reference"],
                             e["account_credit_sales"], "0.00", f"{e['subtotal']:.2f}",
                             f"Venta segun factura {e['reference']}"])
            if e["itbis"] > 0:
                writer.writerow(["FC", e["date"], e["reference"],
                                 e["account_credit_itbis"], "0.00", f"{e['itbis']:.2f}",
                                 "ITBIS factura"])
        return cls._bom_output(output)

    @classmethod
    def _export_expenses_csv_std(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Fecha", "Referencia", "NCF", "Proveedor", "RNC", "Concepto",
                         "Monto", "ITBIS", "Cuenta Débito", "Cuenta Crédito"])
        for e in entries:
            writer.writerow([
                e["date"], e["reference"], e["ncf"],
                e["supplier"], e["rnc"], e["concept"],
                f"{e['amount']:.2f}", f"{e['itbis']:.2f}",
                e["account_debit"], e["account_credit_cxp"],
            ])
            if e["itbis"] > 0:
                writer.writerow([
                    e["date"], e["reference"], e["ncf"],
                    e["supplier"], e["rnc"], "ITBIS Crédito",
                    f"{e['itbis']:.2f}", "0.00",
                    e["account_itbis"], e["account_credit_cxp"],
                ])
        return cls._bom_output(output)

    @classmethod
    def _export_expenses_quickbooks(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["!TRNS", "TRNSID", "TRNSTYPE", "DATE", "ACCNT", "AMOUNT", "DOCNUM", "MEMO"])
        writer.writerow(["!SPL", "SPLID", "TRNSTYPE", "DATE", "ACCNT", "AMOUNT", "DOCNUM", "MEMO"])
        for e in entries:
            writer.writerow(["TRNS", e["reference"], "BILL", e["date"],
                             e["account_credit_cxp"], f"{e['total']:.2f}",
                             e["ncf"], e["concept"]])
            writer.writerow(["SPL", "", "BILL", e["date"],
                             e["account_debit"], f"{-e['amount']:.2f}",
                             e["ncf"], ""])
            if e["itbis"] > 0:
                writer.writerow(["SPL", "", "BILL", e["date"],
                                 e["account_itbis"], f"{-e['itbis']:.2f}",
                                 e["ncf"], "ITBIS Crédito"])
        return cls._bom_output(output)

    @classmethod
    def _export_expenses_sage50(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["ACCTNO", "DATE", "TRNSID", "AMOUNT", "TYPE", "MEMO", "CLEAR"])
        for e in entries:
            writer.writerow([e["account_credit_cxp"], e["date"], e["reference"],
                             f"{e['total']:.2f}", "BILL", e["concept"], "N"])
            writer.writerow([e["account_debit"], e["date"], e["reference"],
                             f"{-e['amount']:.2f}", "BILL", "", "N"])
            if e["itbis"] > 0:
                writer.writerow([e["account_itbis"], e["date"], e["reference"],
                                 f"{-e['itbis']:.2f}", "BILL", "ITBIS Crédito", "N"])
        return cls._bom_output(output)

    @classmethod
    def _export_expenses_odoo(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["account_id", "partner_id", "date", "ref", "debit", "credit"])
        for e in entries:
            writer.writerow([e["account_debit"], e["supplier"], e["date"],
                             e["reference"], f"{e['amount']:.2f}", "0.00"])
            writer.writerow([e["account_itbis"], e["supplier"], e["date"],
                             e["reference"], f"{e['itbis']:.2f}", "0.00"])
            writer.writerow([e["account_credit_cxp"], e["supplier"], e["date"],
                             e["reference"], "0.00", f"{e['total']:.2f}"])
        return cls._bom_output(output)

    @classmethod
    def _export_expenses_softland(cls, entries):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["TIPO", "FECHA", "COMPROBANTE", "CUENTA", "DEBE", "HABER", "DETALLE"])
        for e in entries:
            writer.writerow(["FC", e["date"], e["reference"],
                             e["account_debit"], f"{e['amount']:.2f}", "0.00",
                             e["concept"]])
            if e["itbis"] > 0:
                writer.writerow(["FC", e["date"], e["reference"],
                                 e["account_itbis"], f"{e['itbis']:.2f}", "0.00",
                                 "ITBIS Crédito"])
            writer.writerow(["FC", e["date"], e["reference"],
                             e["account_credit_cxp"], "0.00", f"{e['total']:.2f}",
                             f"Proveedor {e['supplier']}"])
        return cls._bom_output(output)

    @classmethod
    def _bom_output(cls, output):
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        return dest
