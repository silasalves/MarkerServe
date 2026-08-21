# MarkerServe API contract

This document describes the public HTTP contract for MarkerServe API schema version `1`.

The service is intentionally a thin wrapper around the pinned upstream dependency `marker-pdf==2.0.0`. The JSON conversion response is therefore an upstream-derived document tree, not a MarkerServe-specific envelope.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Marker and required VLM readiness |
| `GET` | `/version` | Service, API, dependency, and VLM identity |
| `POST` | `/v1/convert` | Convert one PDF |

## Conversion request

The request is `multipart/form-data` with a required `file` part and these optional fields:

| Field | Values | Notes |
| --- | --- | --- |
| `file` | PDF upload | Filename must end in `.pdf`; content must begin with `%PDF-` |
| `output_format` | `markdown`, `json`, `html` | Defaults to configured `MARKER_OUTPUT_FORMAT` |
| `mode` | `balanced`, `fast` | Passed to Marker |
| `use_llm` | Boolean | Per-request override |
| `force_ocr` | Boolean | Passed to Marker’s PDF provider |
| `page_range` | String | Marker syntax, such as `0,5-10,20` |
| `processors` | String | Comma-separated full Python class paths |
| `disable_image_extraction` | Boolean | Passed to Marker |
| `disable_multiprocessing` | Boolean | Passed to Marker |

Boolean values should be sent as lowercase `true` or `false`. Unknown form fields are rejected. `paginate_output` is not part of this contract.

The default maximum upload size is 50 MiB and can be changed with `MAX_UPLOAD_BYTES`. There is no page-count limit in the service. Conversion concurrency is one request per application process; a request that cannot acquire the slot within `CONVERSION_QUEUE_TIMEOUT_SECONDS` receives `429 conversion_busy`.

## Conversion response

Markdown and HTML are returned as text. JSON is returned as `application/json` and is passed through from Marker’s JSON renderer after parsing and re-serializing at the HTTP boundary.

The expected JSON shape for the pinned upstream version is:

```json
{
  "children": [
    {
      "id": "/page/0",
      "block_type": "Page",
      "html": "<content-ref src='/page/0/Text/0'></content-ref>",
      "polygon": [[0, 0], [612, 0], [612, 792], [0, 792]],
      "bbox": [0, 0, 612, 792],
      "children": [
        {
          "id": "/page/0/Text/0",
          "block_type": "Text",
          "html": "<p>Hello</p>",
          "polygon": [[72, 72], [144, 72], [144, 90], [72, 90]],
          "bbox": [72, 72, 144, 90],
          "children": null,
          "section_hierarchy": null,
          "images": null
        }
      ],
      "section_hierarchy": null
    }
  ],
  "block_type": "Document"
}
```

The upstream renderer preserves reading order in the `children` arrays. Page IDs use the `/page/<page number>` form. `metadata` is deliberately excluded by MarkerServe. Optional `section_hierarchy`, `children`, and `images` fields may be null or populated depending on the block and renderer configuration.

The checked-in JSON fixture is a representative contract fixture for unit tests; it is not a captured GPU conversion. A real conversion fixture is still required before publishing coordinate or image behavior as a stronger guarantee.

This repository currently does not claim a separately normalized coordinate system. Consumers must treat `polygon` and `bbox` as Marker-native geometry until a real conversion fixture establishes the coordinate convention for the deployed upstream version. MarkerServe does not return a separate top-level binary-image payload; image behavior is renderer-dependent and must be verified with an image-containing PDF.

## Version response

`GET /version` returns an object with these fields:

```json
{
  "markerserve_version": "0.1.0",
  "api_schema_version": "1",
  "marker_pdf_version": "2.0.0",
  "python_version": "3.12.0",
  "vlm_mode": "external",
  "vlm_base_url": "http://127.0.0.1:8080/v1",
  "vlm_model": "qwen3.5-9b",
  "marker_use_llm": true,
  "marker_mode": "balanced"
}
```

The API schema version changes when this HTTP contract changes incompatibly. The `marker_pdf_version` is read from the installed package. The conversion response does not contain a version envelope; clients that need provider identity should call `/version` and cache the result.

## Health responses

`/health/live` returns `200` when the process can answer requests:

```json
{"status": "ok", "service": "MarkerServe"}
```

`/health/ready` returns `503` until Marker initialization succeeds. When LLM processing is required, it also checks the configured VLM’s model listing or health endpoint. A successful readiness response has `status: "ready"`; a failed response has `status: "not_ready"` and diagnostic `details`.

## Errors

Errors use this shape:

```json
{
  "error": {
    "code": "conversion_busy",
    "message": "Another conversion is already running",
    "details": null
  }
}
```

Current stable error codes include:

| Status | Code | Meaning |
| --- | --- | --- |
| `413` | `file_too_large` | Upload exceeds the configured limit |
| `415` | `unsupported_file` | Filename is not a PDF filename |
| `415` | `invalid_pdf` | File lacks a PDF signature |
| `422` | `invalid_file` | Missing filename or empty upload |
| `422` | `invalid_conversion_options` | Invalid option value |
| `422` | `unknown_conversion_options` | Unsupported form field |
| `429` | `conversion_busy` | Conversion slot is occupied |
| `500` | `invalid_json_output` | Marker returned invalid JSON for a JSON request |
| `500` | `conversion_failed` | Marker failed during conversion |
| `503` | `marker_unavailable` | Marker is not initialized or available |

There is no application-level conversion timeout or idempotency key. Clients should use bounded timeouts and should retry only according to their deployment policy. A `500` conversion failure must be treated as a provider failure, not as a successful empty result.
