from typing import Literal


def select_model(
    purpose: Literal["consistency", "suggest_local_rule", "suggest_local_gen", "remote_api"] | None = None
) -> None:
    """
    목적에 따른 모델 경로 선택(placeholder).

    예정: 안전 정책 강제, opt-in 스위치, 로컬/원격 라우팅.
    """
    _ = purpose
    raise NotImplementedError("nf_model_gateway.select_model은 placeholder입니다.")
