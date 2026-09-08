"""Regression checks for the Streamlit entrypoint and language reruns."""
import os
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
os.environ["MES_DB_BACKEND"] = "sqlite"


class StreamlitRerunTests(unittest.TestCase):
    def test_language_change_keeps_page_rendered(self):
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[0].value, "en")

        app.selectbox[0].set_value("zh").run()

        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox[0].label, "语言")
        self.assertEqual(app.selectbox[0].value, "zh")
        self.assertIn("SolidWorks 建模", [header.value for header in app.header])

    def test_language_change_inside_mes_keeps_tabs_rendered(self):
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
        next(button for button in app.button if button.label == "MES System").click().run()
        self.assertFalse(app.exception)

        app.selectbox[0].set_value("zh").run()

        self.assertFalse(app.exception)
        self.assertEqual(
            [tab.label for tab in app.tabs],
            ["仪表盘", "创建工单", "工单列表", "生产执行", "质量与缺陷", "追溯"],
        )


if __name__ == "__main__":
    unittest.main()
