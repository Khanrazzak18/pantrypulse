"""The simulator's true demand is for scoring a forecast afterwards, never for building one."""

import ast
import inspect
from pathlib import Path

from app.services import forecasting as fc

APP = Path(fc.__file__).resolve().parents[1]


def test_the_forecasting_module_does_not_import_the_generator_or_its_truth():
    tree = ast.parse(Path(fc.__file__).read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [m for m in imported if m.startswith(("scripts", "eval"))]
    source = Path(fc.__file__).read_text()
    assert "generate_with_truth" not in source and "generate_synthetic_data" not in source


def test_nothing_in_the_app_package_uses_the_latent_demand():
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if "generate_with_truth" in path.read_text() or "scripts.generate" in path.read_text()
    ]
    assert offenders == []


def test_no_training_or_prediction_function_accepts_a_truth_argument():
    for function in (fc.build_frame, fc.build_features, fc.training_rows, fc.fit_models,
                     fc.predict, fc.run_backtest, fc.forward_forecast):  # fmt: skip
        names = " ".join(inspect.signature(function).parameters)
        assert "truth" not in names and "latent" not in names, function.__name__


def test_the_only_user_of_the_truth_is_the_evaluation_script():
    script = Path(__file__).resolve().parents[1] / "eval" / "forecast_backtest.py"
    assert script.exists() and "generate_with_truth" in script.read_text()
