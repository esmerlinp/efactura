def get_ecf_type_number_code(ecf_type):
    if "E31" in ecf_type: return "31"
    if "E32" in ecf_type: return "32"
    if "E33" in ecf_type: return "33"
    if "E34" in ecf_type: return "34"
    if "E41" in ecf_type: return "41"
    if "E43" in ecf_type: return "43"
    if "E44" in ecf_type: return "44"
    if "E45" in ecf_type: return "45"
    if "E46" in ecf_type: return "46"
    if "E47" in ecf_type: return "47"
    return "32"

def get_ecf_type_short_code(ecf_type):
    return f"E{get_ecf_type_number_code(ecf_type)}"
