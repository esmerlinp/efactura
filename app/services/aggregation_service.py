from datetime import datetime, timezone
from typing import Optional
from flask import current_app as app


MONTHLY_SUMMARY_FIELDS = {
    "year": 0,
    "month": 0,
    "total_invoiced": 0.0,
    "total_expenses": 0.0,
    "total_itbis_sales": 0.0,
    "total_itbis_expenses": 0.0,
    "total_cxc": 0.0,
    "total_cxp": 0.0,
    "cxc_vigentes": 0.0,
    "cxc_vencidas": 0.0,
    "cxp_vigentes": 0.0,
    "cxp_vencidas": 0.0,
    "invoice_count": 0,
    "expense_count": 0,
    "cxc_docs_vigentes": 0,
    "cxc_docs_vencidas": 0,
    "cxp_docs_vigentes": 0,
    "cxp_docs_vencidas": 0,
    "products_sold_count": 0,
    "clients_with_sales": 0,
    "pagos_recibidos": 0.0,
    "updated_at": "",
}


class AggregationService:
    @staticmethod
    def _get_db():
        from app.services.db_service import db_firestore
        return db_firestore

    @staticmethod
    def _summary_path(owner_uid: str, year: int, month: int) -> str:
        return f"users/{owner_uid}/monthly_summaries/{year}-{month:02d}"

    @staticmethod
    def get_monthly_summary(owner_uid: str, year: int, month: int) -> Optional[dict]:
        try:
            db = AggregationService._get_db()
            doc = db.document(AggregationService._summary_path(owner_uid, year, month)).get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            app.logger.warning(f"AggregationService.get_monthly_summary error: {e}")
        return None

    @staticmethod
    def recompute_all_months(owner_uid: str, sandbox: bool = False) -> dict:
        from app.services.db_service import DatabaseService

        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)

        real_invoices = [inv for inv in invoices
                        if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]

        monthly_data = {}

        for inv in real_invoices:
            date_str = inv.get('date', '')
            if not date_str:
                continue
            try:
                if 'T' in date_str:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except Exception:
                continue

            key = f"{dt.year}-{dt.month:02d}"
            if key not in monthly_data:
                monthly_data[key] = {**MONTHLY_SUMMARY_FIELDS, "year": dt.year, "month": dt.month}

            m = monthly_data[key]
            m["total_invoiced"] += inv.get('total', 0.0)
            m["total_itbis_sales"] += inv.get('totalITBIS', 0.0)
            m["invoice_count"] += 1

            status = inv.get('status', '')
            if status == 'Emitida':
                m["cxc_vigentes"] += inv.get('netPayable', 0.0)
                m["cxc_docs_vigentes"] += 1
            elif status == 'Vencida':
                m["cxc_vencidas"] += inv.get('netPayable', 0.0)
                m["cxc_docs_vencidas"] += 1

            m["total_cxc"] = m["cxc_vigentes"] + m["cxc_vencidas"]

            if status == 'Pagado':
                m["pagos_recibidos"] += inv.get('netPayable', 0.0)

            for it in inv.get('items', []):
                name = it.get('name', '').lower().strip()
                if name:
                    if 'products_list' not in m:
                        m['products_list'] = set()
                    m['products_list'].add(name)

            client_id = inv.get('clientId', '')
            if client_id:
                if 'clients_list' not in m:
                    m['clients_list'] = set()
                m['clients_list'].add(client_id)

        for exp in expenses:
            date_str = exp.get('date', '')
            if not date_str:
                continue
            try:
                if 'T' in date_str:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except Exception:
                continue

            key = f"{dt.year}-{dt.month:02d}"
            if key not in monthly_data:
                monthly_data[key] = {**MONTHLY_SUMMARY_FIELDS, "year": dt.year, "month": dt.month}

            m = monthly_data[key]
            m["total_expenses"] += exp.get('amount', 0.0)
            m["total_itbis_expenses"] += exp.get('itbisAmount', 0.0)
            m["expense_count"] += 1

            cxp_status = exp.get('cxpStatus', '')
            if exp.get('paymentType') == 'Crédito' and cxp_status != 'Pagado':
                remaining = exp.get('cxpRemainingBalance', 0.0)
                m["total_cxp"] += remaining
                if cxp_status == 'Vencido':
                    m["cxp_vencidas"] += remaining
                    m["cxp_docs_vencidas"] += 1
                else:
                    m["cxp_vigentes"] += remaining
                    m["cxp_docs_vigentes"] += 1

        db = AggregationService._get_db()
        created = 0
        for key, data in monthly_data.items():
            if 'products_list' in data:
                data['products_sold_count'] = len(data.pop('products_list'))
            if 'clients_list' in data:
                data['clients_with_sales'] = len(data.pop('clients_list'))
            data["updated_at"] = datetime.now(timezone.utc).isoformat()

            doc_ref = db.document(f"users/{owner_uid}/monthly_summaries/{key}")
            doc_ref.set(data)
            created += 1

        return {"created": created, "months": list(monthly_data.keys())}

    @staticmethod
    def update_month_for_document(owner_uid: str, doc_date: str):
        try:
            if 'T' in doc_date:
                dt = datetime.fromisoformat(doc_date.replace('Z', '+00:00'))
            else:
                dt = datetime.strptime(doc_date[:10], "%Y-%m-%d")
        except Exception:
            return

        year, month = dt.year, dt.month
        AggregationService.recompute_all_months(owner_uid)

    @staticmethod
    def get_summary_range(owner_uid: str, start_key: str, end_key: str) -> dict:
        try:
            db = AggregationService._get_db()
            docs = db.collection(f"users/{owner_uid}/monthly_summaries") \
                .where(field_path="__name__", op_string=">=", value=start_key) \
                .where(field_path="__name__", op_string="<=", value=end_key) \
                .stream()

            result = {}
            for doc in docs:
                result[doc.id] = doc.to_dict()
            return result
        except Exception as e:
            app.logger.warning(f"AggregationService.get_summary_range error: {e}")
            return {}
