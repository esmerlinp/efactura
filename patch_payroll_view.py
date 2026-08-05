import os
file_path = "templates/rrhh/payroll_view.html"
with open(file_path, "r") as f:
    content = f.read()

content = content.replace('<table class="table-premium"', '<table class="table-premium emp-payroll-table"')

# Add datatables script if not already there
script = """
{% block scripts %}
<script>
document.addEventListener('DOMContentLoaded', function() {
    if (typeof $.fn.DataTable !== 'undefined') {
        $('.emp-payroll-table').DataTable({
            "pageLength": 25,
            "lengthMenu": [[10, 25, 50, 100, -1], [10, 25, 50, 100, "Todos"]],
            "language": {
                "url": "https://cdn.datatables.net/plug-ins/1.13.4/i18n/es-ES.json"
            },
            "dom": '<"d-flex justify-content-between align-items-center mb-3"l>rt<"d-flex justify-content-between align-items-center mt-3"ip>',
            "ordering": true,
            "info": true,
            "searching": false
        });
    }
});
</script>
{% endblock %}
"""

if "emp-payroll-table" in content and "DataTable" not in content:
    if "{% block scripts %}" in content:
        # append inside block scripts
        content = content.replace("{% block scripts %}", script.replace("{% block scripts %}", "{% block scripts %}").replace("{% endblock %}", ""))
    else:
        content += script

    with open(file_path, "w") as f:
        f.write(content)
    print("Patched templates/rrhh/payroll_view.html for DataTables")
else:
    print("Already patched or error")
