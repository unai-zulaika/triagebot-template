import importlib
from unittest.mock import patch


def test_main_loads_dotenv_on_import():
    import app.main

    with patch("dotenv.load_dotenv") as mock_load_dotenv:
        importlib.reload(app.main)

        mock_load_dotenv.assert_called_once()
