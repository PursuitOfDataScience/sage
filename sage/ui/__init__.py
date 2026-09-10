"""The Streamlit view, and the only part of this repository that imports Streamlit.

One module per region of the page, and one — `view.py` — for the thing they are all
handed. `app.py` is the script: it builds the runtime, works out who is asking and
which model they are on, and then calls these in the order the page is laid out.

That order is load-bearing, which is why it lives in one readable list in `app.py`
rather than being implied by where each function happens to be defined. Streamlit
renders in call order, `st.rerun()` means nothing after it runs, and several widgets
here exist only to be found by `static/app.js` in the position they are drawn.
"""

__all__ = [
    "access",
    "assets",
    "composer",
    "landing",
    "sidebar",
    "state",
    "transcript",
    "turn",
    "uploads",
    "view",
]
