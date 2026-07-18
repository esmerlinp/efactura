UNIDADES = [
    "", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    "diez", "once", "doce", "trece", "catorce", "quince", "dieciséis",
    "diecisiete", "dieciocho", "diecinueve", "veinte",
]
VEINTE = [
    "veintiuno", "veintidós", "veintitrés", "veinticuatro",
    "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve",
]
DECENAS = [
    "", "diez", "veinte", "treinta", "cuarenta", "cincuenta",
    "sesenta", "setenta", "ochenta", "noventa",
]
CENTENAS = [
    "", "cien", "doscientos", "trescientos", "cuatrocientos", "quinientos",
    "seiscientos", "setecientos", "ochocientos", "novecientos",
]


def _convertir_centenas(n):
    if n == 0:
        return ""
    if n == 100:
        return "cien"
    centena = n // 100
    resto = n % 100
    base = CENTENAS[centena]
    if centena == 1 and resto > 0:
        base = "ciento"
    if resto == 0:
        return base
    return base + " " + _convertir_decenas(resto)


def _convertir_decenas(n):
    if n == 0:
        return ""
    if n <= 20:
        if n <= 20:
            return UNIDADES[n]
        return ""
    if n <= 29:
        return VEINTE[n - 21]
    d = n // 10
    u = n % 10
    dec = DECENAS[d]
    if u == 0:
        return dec
    if dec == "veinte" and u > 0:
        return "veinti" + UNIDADES[u]
    return dec + " y " + UNIDADES[u]


def _convertir_miles(n):
    if n == 0:
        return ""
    if n < 1000:
        return _convertir_centenas(n)
    miles = n // 1000
    resto = n % 1000
    if miles == 1:
        base = "mil"
    else:
        base = _convertir_centenas(miles) + " mil"
    if resto == 0:
        return base
    return base + " " + _convertir_centenas(resto)


def numero_a_letras(monto):
    if monto < 0:
        return "menos " + numero_a_letras(-monto)
    if monto == 0:
        return "cero pesos dominicanos con 00/100"

    entero = int(monto)
    decimales = int(round((monto - entero) * 100))

    partes = []

    millones = entero // 1000000
    miles = entero % 1000000

    if millones == 1:
        partes.append("un millón")
    elif millones > 1:
        partes.append(_convertir_miles(millones) + " millones")

    if miles > 0:
        partes.append(_convertir_miles(miles))

    texto = " ".join(p for p in partes if p).strip()
    if texto.startswith("uno ") or texto == "uno":
        texto = "un" + texto[3:] if texto.startswith("uno ") else "un"

    if texto.startswith("un millón"):
        if texto == "un millón":
            texto = "un millón de"
        elif " de " not in texto[:20]:
            texto = texto.replace("un millón ", "un millón de ", 1)

    texto = texto + f" pesos dominicanos con {decimales:02d}/100"

    return texto
