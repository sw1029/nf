from __future__ import annotations


def validate_job_params(handler, job_type, params) -> None:
    # Adapter stub for incremental validator extraction.
    return handler._validate_job_params(job_type, params)


def validate_extraction_mapping_payload(handler, payload, *, partial: bool):
    # Adapter stub for incremental validator extraction.
    return handler._validate_extraction_mapping_payload(payload, partial=partial)
