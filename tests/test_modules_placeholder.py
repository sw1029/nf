import importlib
from typing import Callable

import pytest


PLACEHOLDER_MODULE_SPECS = [
    ("modules.nf_desktop", "launch_app"),
]

IMPLEMENTED_MODULES = [
    "modules.nf_workers",
    "modules.nf_schema",
    "modules.nf_retrieval",
    "modules.nf_consistency",
    "modules.nf_model_gateway",
    "modules.nf_export",
]


@pytest.mark.smoke
@pytest.mark.placeholder
@pytest.mark.parametrize("module_path, func_name", PLACEHOLDER_MODULE_SPECS)
def test_placeholder_functions_raise_not_implemented(module_path: str, func_name: str) -> None:
    module = importlib.import_module(module_path)
    placeholder: Callable[..., object] = getattr(module, func_name)

    with pytest.raises(NotImplementedError) as exc:
        placeholder()  # type: ignore[arg-type]

    assert "placeholder" in str(exc.value).lower()


@pytest.mark.unit
@pytest.mark.placeholder
@pytest.mark.parametrize("module_path, _", PLACEHOLDER_MODULE_SPECS)
def test_placeholder_versions(module_path: str, _: str) -> None:
    module = importlib.import_module(module_path)
    assert hasattr(module, "__version__")
    assert isinstance(module.__version__, str)
    assert module.__version__.endswith("placeholder")


@pytest.mark.unit
@pytest.mark.parametrize("module_path", IMPLEMENTED_MODULES)
def test_implemented_versions(module_path: str) -> None:
    module = importlib.import_module(module_path)
    assert hasattr(module, "__version__")
    assert isinstance(module.__version__, str)
    assert not module.__version__.endswith("placeholder")
