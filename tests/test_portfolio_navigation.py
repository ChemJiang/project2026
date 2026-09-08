import ast
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
STREAMLIT_ENTRYPOINT = ROOT / "streamlit_app.py"
ASSET_DIR = ROOT / "assets" / "solidworks"
ANYLOGIC_DIR = ROOT / "data" / "anylogic"


class PortfolioNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_four_top_level_sections_are_ordered(self):
        assignment = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "MAIN_SECTION_KEYS" for target in node.targets)
        )
        self.assertEqual(
            ast.literal_eval(assignment.value),
            ["solidworks", "anylogic", "mes_system", "six_sigma"],
        )

    def test_mes_tabs_exclude_six_sigma(self):
        assignment = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PAGE_KEYS" for target in node.targets)
        )
        self.assertEqual(
            ast.literal_eval(assignment.value),
            [
                "dashboard",
                "create_work_order",
                "work_order_list",
                "production_execution",
                "quality_defects",
                "traceability",
            ],
        )

    def test_solidworks_assets_exist(self):
        expected = [
            "assembly_isometric.png",
            "SW_Agricultural_Manipulator_Portfolio.zip",
        ]
        for name in expected:
            path = ASSET_DIR / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 0, name)

    def test_solidworks_source_archive_is_valid(self):
        archive = ASSET_DIR / "SW_Agricultural_Manipulator_Portfolio.zip"
        with zipfile.ZipFile(archive) as package:
            self.assertIsNone(package.testzip())
            names = package.namelist()
        self.assertTrue(any(name.lower().endswith(".sldasm") for name in names))
        self.assertTrue(any(name.lower().endswith(".sldprt") for name in names))

    def test_solidworks_demo_video_exists(self):
        video = ROOT / "A_final_Robotic Arm.mp4"
        self.assertTrue(video.is_file())
        self.assertGreater(video.stat().st_size, 0)

    def test_anylogic_evidence_is_bundled(self):
        expected = [
            "RoboticArmMES.alp",
            "anylogic_high_demand_2operators.png",
            "anylogic_high_demand_3operators.png",
            "robotic_arm_process_routing_2_with_30_replications_checked.xlsx",
        ]
        for name in expected:
            path = ANYLOGIC_DIR / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 0, name)

    def test_app_uses_repository_local_anylogic_service(self):
        entrypoint = STREAMLIT_ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("anylogic_cloud_service", entrypoint)
        self.assertIn('sys.modules["services.anylogic_service"]', entrypoint)


if __name__ == "__main__":
    unittest.main()
