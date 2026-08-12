with open("templates/certificacion/step_02_datos_ecf.html", "r") as f:
    text = f.read()

# Update generateStep2Group request payload
old_body = """                body: { 
                    parsed_data: parsedStep2Data,
                    dry_run: dryRun, 
                    groups: groups, 
                    resume_run: resumeRun 
                },"""

new_body = """                body: { 
                    parsed_data: parsedStep2Data,
                    dry_run: dryRun, 
                    groups: groups, 
                    resume_run: resumeRun,
                    force_rerun: true
                },"""

text = text.replace(old_body, new_body)

with open("templates/certificacion/step_02_datos_ecf.html", "w") as f:
    f.write(text)

print("Force rerun added to UI")
