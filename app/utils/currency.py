import requests
import time

class CurrencyService:
    _usd_to_dop = 58.50
    _eur_to_dop = 63.20
    _last_fetched = 0.0
    _cache_duration = 3600  # 1 hora

    @classmethod
    def fetch_rates(cls, force=False):
        """Obtiene las tasas de cambio de USD y EUR a DOP desde open.er-api.com."""
        current_time = time.time()
        if not force and (current_time - cls._last_fetched) < cls._cache_duration:
            return {
                "USD": cls._usd_to_dop,
                "EUR": cls._eur_to_dop,
                "cached": True,
                "last_updated": cls._last_fetched
            }

        url = "https://open.er-api.com/v6/latest/USD"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("result") == "success":
                    rates = data.get("rates", {})
                    dop_rate = rates.get("DOP")
                    eur_rate = rates.get("EUR")

                    if dop_rate:
                        cls._usd_to_dop = float(dop_rate)
                    
                    if eur_rate and dop_rate:
                        # 1 EUR = (1.0 / eur_rate) USD = (1.0 / eur_rate) * dop_rate DOP
                        cls._eur_to_dop = float((1.0 / eur_rate) * dop_rate)
                    
                    cls._last_fetched = current_time
                    print(f"✅ CurrencyService: Tasas actualizadas. USD: {cls._usd_to_dop:.2f}, EUR: {cls._eur_to_dop:.2f}")
                    return {
                        "USD": cls._usd_to_dop,
                        "EUR": cls._eur_to_dop,
                        "cached": False,
                        "last_updated": cls._last_fetched
                    }
            print(f"⚠️ CurrencyService: Error de API ({response.status_code}). Usando tasas en caché.")
        except requests.RequestException as e:
            print(f"❌ CurrencyService: Excepción de red ({str(e)}). Usando tasas en caché.")

        return {
            "USD": cls._usd_to_dop,
            "EUR": cls._eur_to_dop,
            "cached": True,
            "error": True,
            "last_updated": cls._last_fetched
        }

    @classmethod
    def get_rate(cls, currency):
        """Devuelve la tasa de conversión para DOP de la moneda dada."""
        currency = str(currency).upper()
        if currency == "USD":
            cls.fetch_rates()
            return cls._usd_to_dop
        elif currency == "EUR":
            cls.fetch_rates()
            return cls._eur_to_dop
        return 1.0  # DOP u otras
