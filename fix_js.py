with open("templates/certificacion/step_02_datos_ecf.html", "r") as f:
    text = f.read()

text = text.replace(
    "const r = globalDataState?.results?.find(res => res.encf === c.encf);",
    "const r = globalDataState?.results?.find(res => res.encf === c.encf && res.grupo === g);"
)

text = text.replace(
    "const idx = globalDataState.results.findIndex(r => r.encf === newR.encf);",
    "const idx = globalDataState.results.findIndex(r => r.encf === newR.encf && r.grupo === newR.grupo);"
)

with open("templates/certificacion/step_02_datos_ecf.html", "w") as f:
    f.write(text)
