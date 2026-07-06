import csv
import io
import re
from datetime import datetime
from typing import Optional


class BankStatementParser:
    SUPPORTED_BANKS = ["popular", "bhd", "banreservas", "generic"]

    @classmethod
    def parse_csv(cls, content: bytes, bank: str = "generic") -> list:
        text = content.decode("utf-8-sig").strip()
        if bank == "popular":
            return cls._parse_popular(text)
        elif bank == "bhd":
            return cls._parse_bhd(text)
        elif bank == "banreservas":
            return cls._parse_banreservas(text)
        else:
            return cls._parse_generic(text)

    @classmethod
    def _parse_popular(cls, text: str) -> list:
        reader = csv.reader(io.StringIO(text))
        transactions = []
        in_data = False
        for row in reader:
            if not row or len(row) < 4:
                continue
            if "Fecha" in row[0] and "Descripción" in " ".join(row):
                in_data = True
                continue
            if not in_data:
                continue
            try:
                date_str = row[0].strip()
                description = row[1].strip() if len(row) > 1 else ""
                amount_str = row[-1].strip() if len(row) > 2 else "0"
                amount = cls._parse_amount(amount_str)

                txn_type = "income" if amount > 0 else "expense"
                transactions.append({
                    "date": cls._normalize_date(date_str),
                    "description": description,
                    "amount": abs(amount),
                    "type": txn_type,
                    "bank": "popular",
                })
            except Exception:
                continue
        return transactions

    @classmethod
    def _parse_bhd(cls, text: str) -> list:
        return cls._parse_generic(text, bank="bhd")

    @classmethod
    def _parse_banreservas(cls, text: str) -> list:
        return cls._parse_generic(text, bank="banreservas")

    @classmethod
    def _parse_generic(cls, text: str, bank: str = "generic") -> list:
        reader = csv.reader(io.StringIO(text))
        transactions = []
        headers = None
        for row in reader:
            if not row or len(row) < 3:
                continue
            if headers is None:
                headers = [h.lower().strip() for h in row]
                continue
            try:
                data = dict(zip(headers, row))
                date_str = cls._get_date_field(data)
                description = cls._get_description_field(data)
                amount = cls._get_amount_field(data)

                txn_type = "income" if amount > 0 else "expense"
                transactions.append({
                    "date": cls._normalize_date(date_str),
                    "description": description,
                    "amount": abs(amount),
                    "type": txn_type,
                    "bank": bank,
                })
            except Exception:
                continue
        return transactions

    @classmethod
    def _parse_amount(cls, value: str) -> float:
        value = value.replace("RD$", "").replace("$", "").strip()
        value = re.sub(r"[^\d.,\-]", "", value)
        value = value.replace(",", "")
        try:
            return float(value)
        except ValueError:
            return 0.0

    @classmethod
    def _normalize_date(cls, date_str: str) -> str:
        formats = ["%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y%m%d"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str.strip()

    @classmethod
    def _get_date_field(cls, data: dict) -> str:
        for key in data:
            if "fecha" in key or "date" in key:
                return data[key]
        return list(data.values())[0] if data else ""

    @classmethod
    def _get_description_field(cls, data: dict) -> str:
        for key in data:
            if "descrip" in key or "concepto" in key or "detalle" in key:
                return data[key]
        return list(data.values())[1] if len(data) > 1 else ""

    @classmethod
    def _get_amount_field(cls, data: dict) -> float:
        for key in data:
            if "monto" in key or "amount" in key or "importe" in key:
                return cls._parse_amount(data[key])
        for val in data.values():
            try:
                return cls._parse_amount(val)
            except Exception:
                continue
        return 0.0

    @classmethod
    def auto_match(cls, statement_txns: list, book_txns: list) -> list:
        results = []
        unmatched_book = list(book_txns)

        for stmt_txn in statement_txns:
            match = None
            match_score = 0

            for i, book_txn in enumerate(unmatched_book):
                score = cls._match_score(stmt_txn, book_txn)
                if score > match_score:
                    match_score = score
                    match = i

            result = {**stmt_txn, "matched": False, "book_match": None}
            if match is not None and match_score >= 2:
                result["matched"] = True
                result["book_match"] = unmatched_book.pop(match)["id"]

            results.append(result)

        for book_txn in unmatched_book:
            results.append({
                "date": book_txn.get("date", ""),
                "description": book_txn.get("description", ""),
                "amount": abs(book_txn.get("amount", 0)),
                "type": book_txn.get("type", ""),
                "bank": "book",
                "matched": False,
                "book_match": book_txn["id"],
                "unmatched_book": True,
            })

        return results

    @classmethod
    def _match_score(cls, stmt: dict, book: dict) -> int:
        score = 0
        if abs(stmt.get("amount", 0) - abs(book.get("amount", 0))) < 0.01:
            score += 3
        if abs(stmt.get("amount", 0) - abs(book.get("amount", 0))) < 10.0:
            score += 1

        stmt_date = stmt.get("date", "")
        book_date = book.get("date", "")
        if stmt_date and book_date:
            try:
                d1 = datetime.strptime(stmt_date[:10], "%Y-%m-%d")
                d2 = datetime.strptime(book_date[:10], "%Y-%m-%d")
                diff = abs((d1 - d2).days)
                if diff <= 1:
                    score += 3
                elif diff <= 3:
                    score += 1
            except Exception:
                pass

        return score
