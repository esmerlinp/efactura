import requests
import time
from app.cache import cache
import re


class CurrencyService:
    CACHE_KEY_RATES = 'currency_exchange_rates'
    CACHE_KEY_BPD = 'currency_bpd_rate'
    CACHE_TTL = 3600
    BPD_CACHE_TTL = 1800

    @classmethod
    def fetch_rates(cls, force=False):
        """Obtiene las tasas de cambio de USD y EUR a DOP desde open.er-api.com."""
        if not force:
            cached = cache.get(cls.CACHE_KEY_RATES)
            if cached:
                return {**cached, "cached": True}

        url = "https://open.er-api.com/v6/latest/USD"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("result") == "success":
                    rates = data.get("rates", {})
                    dop_rate = rates.get("DOP")
                    eur_rate = rates.get("EUR")

                    usd_to_dop = float(dop_rate) if dop_rate else None

                    if eur_rate and dop_rate:
                        eur_to_dop = float((1.0 / eur_rate) * dop_rate)
                    else:
                        eur_to_dop = None

                    now = time.time()
                    result = {
                        "USD": usd_to_dop,
                        "EUR": eur_to_dop,
                        "cached": False,
                        "last_updated": now
                    }
                    cache.set(cls.CACHE_KEY_RATES, result, timeout=cls.CACHE_TTL)
                    print(f"✅ CurrencyService: Tasas actualizadas. USD: {usd_to_dop:.2f}, EUR: {eur_to_dop:.2f}")
                    return result

            print(f"⚠️ CurrencyService: Error de API ({response.status_code}). Usando tasas en caché.")
        except requests.RequestException as e:
            print(f"❌ CurrencyService: Excepción de red ({str(e)}). Usando tasas en caché.")

        cached = cache.get(cls.CACHE_KEY_RATES)
        if cached:
            return {**cached, "cached": True, "error": True}

        return {
            "USD": 58.50,
            "EUR": 63.20,
            "cached": True,
            "error": True,
            "last_updated": 0.0
        }

    @classmethod
    def get_rate(cls, currency):
        """Devuelve la tasa de conversión para DOP de la moneda dada."""
        currency = str(currency).upper()
        if currency == "USD":
            return cls.get_bpd_rate()
        elif currency == "EUR":
            rates = cls.fetch_rates()
            return rates.get("EUR", 63.20)
        return 1.0

    @classmethod
    def get_bpd_rate(cls):
        """Obtiene la tasa de venta del USD desde Banco Popular Dominicano o fallback."""
        cached = cache.get(cls.CACHE_KEY_BPD)
        if cached:
            return cached

        url = "https://popularenlinea.com/personas/Paginas/tasa-de-cambio.aspx"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                html = response.text
                candidates = re.findall(r'\b(5[6-9]\.\d{2,4})\b', html)
                if candidates:
                    rates = sorted(list(set([float(c) for c in candidates if 56.5 <= float(c) <= 61.5])))
                    if len(rates) >= 2:
                        venta = rates[1]
                        print(f"✅ CurrencyService BPD: Scraped USD Venta: {venta:.2f}")
                        cache.set(cls.CACHE_KEY_BPD, venta, timeout=cls.BPD_CACHE_TTL)
                        return venta
        except Exception as e:
            print(f"⚠️ Error al raspar tasas del BPD: {e}")

        rates = cls.fetch_rates()
        dop = rates.get("USD", 58.50)
        cache.set(cls.CACHE_KEY_BPD, dop, timeout=cls.BPD_CACHE_TTL)
        return dop
