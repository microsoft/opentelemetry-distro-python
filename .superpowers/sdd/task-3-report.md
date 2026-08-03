# Task 3 Report

## Status
- Complete.

## Files Changed
- `build/getting_started_with_kairo_exporter/README.md`
- `build/getting_started_with_kairo_exporter/src/agent.py`
- `build/getting_started_with_kairo_exporter/src/start_server.py`
- `build/getting_started_with_kairo_exporter/tests/test_guardrail_service.py`
- `build/getting_started_with_kairo_exporter/tests/test_sample_wiring.py`

## Commit
- `a8e35099f9bddd2c481aced0542dce1472663f5b` — `feat: instrument Kairo sample guardrail span`

## TDD / Verification Log

### Red: focused wiring test before implementation
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; python -m pytest -o addopts='' build\getting_started_with_kairo_exporter\tests\test_guardrail_service.py::test_deny_trigger_is_case_insensitive build\getting_started_with_kairo_exporter\tests\test_sample_wiring.py -v
```
Result:
- `test_deny_trigger_is_case_insensitive` passed.
- `test_agent_imports_guardrail_service_and_types` failed (`evaluate_input_guardrail` import missing).
- `test_on_message_evaluates_guardrail_before_downstream_processing` failed (`evaluate_input_guardrail` call missing).
- `test_start_server_registers_payload_logging_after_configure` failed (`register_guardrail_payload_logging` import missing).
- Session summary: `3 failed, 1 passed`.

### Green: focused wiring test after implementation
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; python -m pytest -o addopts='' build\getting_started_with_kairo_exporter\tests\test_guardrail_service.py::test_deny_trigger_is_case_insensitive build\getting_started_with_kairo_exporter\tests\test_sample_wiring.py -v
```
Result:
- `4 passed in 1.14s`.

### Sample-local test suite
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; python -m pytest -o addopts='' build\getting_started_with_kairo_exporter\tests -v
```
Result:
- `8 passed in 1.16s`.

### Repository guardrail/exporter regressions
Command:
```powershell
$env:PYTHONPATH='src'; python -m pytest -o addopts='' tests\a365\test_apply_guardrail_scope.py tests\a365\test_exporter.py -v
```
Result:
- `58 passed, 4 subtests passed in 1.34s`.

### Saved payload artifact JSON validation
Command:
```powershell
python -c "import json, pathlib; p=pathlib.Path(r'C:\Users\nikhilc\repos\opentelemetry-distro-python\.superpowers\sdd\kairo-guardrail-payload.json'); json.loads(p.read_text(encoding='utf-8')); print('json-ok')"
```
Result:
- `json-ok`

## Actual Payload Capture Command and Artifact
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; $env:ENABLE_OBSERVABILITY='true'; @'
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from microsoft.opentelemetry.a365.core import AgentDetails, Request
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from services.guardrail_service import evaluate_input_guardrail
from utils.payload_logging_exporter import (
    PAYLOAD_END_MARKER,
    PAYLOAD_START_MARKER,
    GuardrailPayloadLoggingExporter,
)

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(GuardrailPayloadLoggingExporter()))
OpenTelemetryScope._tracer = provider.get_tracer('kairo-payload-capture')
output = StringIO()
try:
    with redirect_stdout(output):
        evaluate_input_guardrail(
            'What is the weather?',
            AgentDetails(
                agent_id='agent-123',
                agent_name='Kairo Guardrail Sample',
                tenant_id='tenant-456',
            ),
            Request(conversation_id='conversation-789'),
        )
finally:
    provider.shutdown()
    OpenTelemetryScope._tracer = None

text = output.getvalue()
body = text.split(PAYLOAD_START_MARKER, 1)[1].split(PAYLOAD_END_MARKER, 1)[0].strip()
json.loads(body)
artifact = Path(r'C:\Users\nikhilc\repos\opentelemetry-distro-python\.superpowers\sdd\kairo-guardrail-payload.json')
artifact.write_text(body, encoding='utf-8')
print(body)
print(f'\nArtifact: {artifact}')
'@ | python -
```
Artifact:
- `C:\Users\nikhilc\repos\opentelemetry-distro-python\.superpowers\sdd\kairo-guardrail-payload.json`

## Self-Review
- Guardrail evaluation is now invoked immediately after `invoke_scope.record_input_messages([user_message])`.
- Denied requests return after `context.send_activity(...)` before token exchange, tool execution, or Azure OpenAI calls; this is enforced by `test_on_message_evaluates_guardrail_before_downstream_processing`.
- `start_server.py` registers the sample-only payload logger immediately after normal `configure(...)`, preserving the normal exporter path while teeing the exact serialized guardrail payload.
- README now documents the deterministic allow/deny examples, non-sensitive fixed content policy, and the printed JSON envelope.
- Payload artifact contains a real allow-span export body with runtime-generated IDs/timestamps and was validated with `json.loads(...)`.

## Concerns
- No functional concerns.
- The denied-path ordering check is source-structure based (`ast`) because the sample's Microsoft Agents runtime dependencies are not installed in this repository environment; the enforced ordering still matches the requirement and is covered by the focused wiring test.

## Fix Review Findings

### Red: review-finding regression coverage before implementation
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; python -m pytest -o addopts='' build\getting_started_with_kairo_exporter\tests\test_sample_wiring.py build\getting_started_with_kairo_exporter\tests\test_payload_logging_exporter.py::test_guardrail_payload_uses_active_parent_span_id -v
```
Result:
- `test_sample_wiring.py` failed during collection with `ModuleNotFoundError: No module named 'services.message_pipeline'`.
- Session summary: `1 error in 1.81s`.

### Green: review-finding regression coverage after implementation
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; python -m pytest -o addopts='' build\getting_started_with_kairo_exporter\tests\test_sample_wiring.py build\getting_started_with_kairo_exporter\tests\test_payload_logging_exporter.py::test_guardrail_payload_uses_active_parent_span_id -v
```
Result:
- `5 passed in 1.19s`.

### Kairo sample test suite after review fixes
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; python -m pytest -o addopts='' build\getting_started_with_kairo_exporter\tests -v
```
Result:
- `10 passed in 1.23s`.

### Repository guardrail/exporter regressions after review fixes
Command:
```powershell
$env:PYTHONPATH='src'; python -m pytest -o addopts='' tests\a365\test_apply_guardrail_scope.py tests\a365\test_exporter.py -v
```
Result:
- `58 passed, 4 subtests passed in 1.39s`.

### Regenerated payload artifact validation
Command:
```powershell
$env:PYTHONPATH='src;build\getting_started_with_kairo_exporter\src'; $env:ENABLE_OBSERVABILITY='true'; @'
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from microsoft.opentelemetry.a365.core import AgentDetails, Request
from microsoft.opentelemetry.a365.core.opentelemetry_scope import OpenTelemetryScope
from services.guardrail_service import evaluate_input_guardrail
from utils.payload_logging_exporter import (
    PAYLOAD_END_MARKER,
    PAYLOAD_START_MARKER,
    GuardrailPayloadLoggingExporter,
)

provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(GuardrailPayloadLoggingExporter()))
tracer = provider.get_tracer('kairo-payload-capture')
OpenTelemetryScope._tracer = tracer
output = StringIO()
try:
    with redirect_stdout(output):
        with tracer.start_as_current_span('invoke_agent parent') as parent_span:
            evaluate_input_guardrail(
                'What is the weather?',
                AgentDetails(
                    agent_id='agent-123',
                    agent_name='Kairo Guardrail Sample',
                    tenant_id='tenant-456',
                ),
                Request(conversation_id='conversation-789'),
            )
            parent_span_id = f"{parent_span.get_span_context().span_id:016x}"
finally:
    provider.shutdown()
    OpenTelemetryScope._tracer = None

text = output.getvalue()
body = text.split(PAYLOAD_START_MARKER, 1)[1].split(PAYLOAD_END_MARKER, 1)[0].strip()
payload = json.loads(body)
span = payload['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
assert span['parentSpanId'] == parent_span_id
artifact = Path(r'C:\Users\nikhilc\repos\opentelemetry-distro-python\.superpowers\sdd\kairo-guardrail-payload.json')
artifact.write_text(body, encoding='utf-8')
print('json-ok')
print(f'parent-span-id={parent_span_id}')
print(f'artifact={artifact}')
'@ | python -
```
Result:
- `json-ok`
- `parent-span-id=5b0914864661df6b`
- `artifact=C:\Users\nikhilc\repos\opentelemetry-distro-python\.superpowers\sdd\kairo-guardrail-payload.json`
