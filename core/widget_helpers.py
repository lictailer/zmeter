"""Small Qt widget helpers shared by the scan editor modules."""


def clearLayout(layout):
    """Remove and schedule deletion of every widget in ``layout``."""
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()


def is_float(element: any) -> bool:
    """Return True when ``element`` can be converted to a float."""
    # If you expect None to be passed:
    if element is None:
        return False
    if element == "":
        return False
    try:
        float(element)
        return True
    except ValueError:
        return False
