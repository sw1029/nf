import pytest

from modules.nf_export import contracts


@pytest.mark.unit
def test_exporter_protocol_methods_exist() -> None:
    assert hasattr(contracts, "Exporter")
    assert hasattr(contracts.Exporter, "export_txt")
    assert hasattr(contracts.Exporter, "export_docx")

