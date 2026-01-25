from typing import Literal


def select_model(
    purpose: Literal["consistency", "suggest_local_rule", "suggest_local_gen", "remote_api"] | None = None
) -> None:
    """
    Choose model path based on purpose (placeholder).

    Planned: enforce safety, opt-in switches, and routing to local/remote providers.
    """
    _ = purpose
    raise NotImplementedError("nf_model_gateway.select_model is a placeholder.")
