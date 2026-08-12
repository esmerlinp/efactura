with open("templates/certificacion/step_02_datos_ecf.html", "r") as f:
    text = f.read()

text = text.replace(
    """                showStep2Results({
                    total: lastRun.total_cases,
                    accepted: lastRun.accepted,
                    rejected: lastRun.rejected,
                    results: lastRun.cases,
                    run_number: lastRun.run_number,
                });""",
    """                globalDataState = {
                    total: lastRun.total_cases,
                    accepted: lastRun.accepted,
                    rejected: lastRun.rejected,
                    results: lastRun.cases,
                    run_number: lastRun.run_number,
                };
                renderGroups();"""
)

with open("templates/certificacion/step_02_datos_ecf.html", "w") as f:
    f.write(text)

print("Replaced init successfully")
