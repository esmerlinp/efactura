import os
file_path = "app/__init__.py"
with open(file_path, "r") as f:
    content = f.read()

target = "@app.context_processor"
replacement = """@app.after_request
    def log_session(response):
        import flask
        print(f"==============================")
        print(f"ACTIVE SESSION: {flask.session}")
        print(f"==============================")
        return response

    @app.context_processor"""

if "log_session" not in content and target in content:
    with open(file_path, "w") as f:
        f.write(content.replace(target, replacement))
    print("Patched app/__init__.py to log session")
else:
    print("Already patched or target not found")
