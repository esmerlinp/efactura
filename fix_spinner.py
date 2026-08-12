with open("templates/certificacion/step_02_datos_ecf.html", "r") as f:
    text = f.read()

# Remove the spinner span
text = text.replace(
    """                        </button>\n                        <span id="spinner-group-${g}" style="display:none;" class="cert-progress-spinner">Cargando...</span>\n                     </div>""",
    """                        </button>\n                     </div>"""
)

# Update generateStep2Group loading start
old_start = """        if (btn) btn.disabled = true;
        if (spinner) spinner.style.display = "inline-block";"""

new_start = """        if (btn) {
            btn.disabled = true;
            btn.dataset.originalHtml = btn.innerHTML;
            btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Procesando...`;
            btn.style.opacity = "0.8";
        }"""

text = text.replace(old_start, new_start)

# Update generateStep2Group loading end (success/try)
old_end1 = """            if (btn) btn.disabled = false;
            if (spinner) spinner.style.display = "none";"""

new_end1 = """            if (btn) {
                btn.disabled = false;
                btn.innerHTML = btn.dataset.originalHtml;
                btn.style.opacity = "1";
            }"""

text = text.replace(old_end1, new_end1)

# Update generateStep2Group loading end (catch)
old_end2 = """            if (btn) btn.disabled = false;
            if (spinner) spinner.style.display = "none";"""

text = text.replace(old_end2, new_end1)

with open("templates/certificacion/step_02_datos_ecf.html", "w") as f:
    f.write(text)

print("Spinner logic updated")
