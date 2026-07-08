"""Gunicorn entry-point — exposes `server` for `gunicorn app:server`."""
from dash_doenças_e_agravos import app  # noqa: F401

server = app.server

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
