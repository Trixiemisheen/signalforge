from pathlib import Path


def test_frontend_html_exists():
    """Ensure the HTML frontend exists after removing Streamlit"""
    project_root = Path(__file__).resolve().parents[1]
    html = project_root / "web" / "templates" / "index.html"
    assert html.exists()

