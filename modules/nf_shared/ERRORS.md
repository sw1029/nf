# 오류 코드

이 문서는 API 응답에 사용하는 공통 오류 코드를 정리한다.

| 코드 | 의미 | 대표 원인 |
| --- | --- | --- |
| VALIDATION_ERROR | 요청 본문/파라미터가 유효하지 않음 | 필드 누락/유효성 오류/타입 불일치 |
| NOT_FOUND | 리소스를 찾을 수 없음 | project_id/job_id 등 미존재 |
| POLICY_VIOLATION | 정책 위반 | 루프백 제한, sync 벡터 쿼리, 토큰 미설정 |
| INTERNAL_ERROR | 서버 내부 오류 | 예기치 못한 예외 |
