def _contrast_text_color(hex_color: str) -> str:
    """Returns #FFFFFF for dark backgrounds and #000000 for light backgrounds based on perceived luminance."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    if len(hex_color) != 6:
        return '#FFFFFF'
    try:
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        # Rec. 709 luminance formula
        luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b)
        return '#000000' if luminance > 128 else '#FFFFFF'
    except ValueError:
        return '#FFFFFF'
