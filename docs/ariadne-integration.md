# Ariadne integration notes

These notes describe how a client such as Ariadne should replace the legacy Marker web-server integration.

## Request mapping

Use `POST /v1/convert` with the PDF in the `file` multipart field and request `output_format=json`.

Do not send the legacy `paginate_output` field. MarkerServe rejects unknown form fields.

The response is the direct Marker document tree. It is not wrapped in Ariadne’s previous `success`, `format`, `output`, `images`, or `version` envelope.

## Health and version

Use `/health/ready` for service admission and recovery checks. Use `/health/live` for process-level monitoring. Call `/version` separately and cache the result as provider metadata; the conversion response does not include a version field.

Readiness does not need to be polled before every individual conversion. A client can check it during startup, after a `503`, or through a background health monitor. The client should still handle conversion-time `503 marker_unavailable` responses.

## Retry and fallback policy

Bounded retries are appropriate for `429 conversion_busy` and transient `503` responses. There is no durable job identifier or idempotency key, so retries should be limited and observable.

`500 conversion_failed` and `500 invalid_json_output` are provider failures. The client should preserve that provider failure and must not silently substitute a different OCR provider unless that behavior is an explicit higher-level policy.

## JSON and geometry

The JSON tree follows the pinned upstream Marker renderer. Page and block nodes use `children`, `id`, `block_type`, `html`, `polygon`, and `bbox`, with optional nested fields.

The client should not assume MinerU geometry semantics. Until a real Marker conversion fixture is captured, coordinates should be stored as Marker-native geometry and should not be silently converted or labeled as another provider’s coordinate system.

Image extraction and visual-description behavior must be tested with an image-containing PDF. MarkerServe does not return a separate top-level binary-image response.
