from __future__ import annotations

import ast
from pathlib import Path


SAMPLE_SRC = Path(__file__).parents[1] / "src"


def _parse_module(filename: str) -> ast.Module:
    return ast.parse((SAMPLE_SRC / filename).read_text(encoding="utf-8"))


def _find_imported_name(module: ast.Module, module_name: str, name: str) -> ast.alias | None:
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            for imported_name in node.names:
                if imported_name.name == name:
                    return imported_name
    return None


def _find_function(module: ast.Module, function_name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in module.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
            return node
    raise AssertionError(f"Could not find function {function_name!r}.")


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        root_name = _call_name(node.value)
        if root_name is None:
            return None
        return f"{root_name}.{node.attr}"
    return None


def _statement_contains_call(statement: ast.stmt, call_name: str) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == call_name for node in ast.walk(statement)
    )


def test_agent_imports_guardrail_service_and_types():
    module = _parse_module("agent.py")

    guardrail_import = _find_imported_name(
        module,
        "services.guardrail_service",
        "evaluate_input_guardrail",
    )
    assert guardrail_import is not None

    agent_details_alias = _find_imported_name(
        module,
        "microsoft.opentelemetry.a365.core",
        "AgentDetails",
    )
    request_alias = _find_imported_name(
        module,
        "microsoft.opentelemetry.a365.core",
        "Request",
    )
    assert agent_details_alias is not None
    assert agent_details_alias.asname == "GuardrailAgentDetails"
    assert request_alias is not None
    assert request_alias.asname == "GuardrailRequest"


def test_on_message_evaluates_guardrail_before_downstream_processing():
    module = _parse_module("agent.py")
    on_message = _find_function(module, "on_message")
    invoke_scope_with = next(
        node
        for node in ast.walk(on_message)
        if isinstance(node, ast.With)
        and any(_call_name(item.context_expr) == "invoke_scope" for item in node.items)
    )

    statement_indexes: dict[str, int] = {}
    for index, statement in enumerate(invoke_scope_with.body):
        for call_name in (
            "evaluate_input_guardrail",
            "AGENT_APP.auth.exchange_token",
            "execute_tool",
            "call_azure_openai",
        ):
            if call_name not in statement_indexes and _statement_contains_call(statement, call_name):
                statement_indexes[call_name] = index

    assert statement_indexes["evaluate_input_guardrail"] < statement_indexes["AGENT_APP.auth.exchange_token"]
    assert statement_indexes["evaluate_input_guardrail"] < statement_indexes["execute_tool"]
    assert statement_indexes["evaluate_input_guardrail"] < statement_indexes["call_azure_openai"]

    guardrail_assignment = invoke_scope_with.body[statement_indexes["evaluate_input_guardrail"]]
    assert isinstance(guardrail_assignment, ast.Assign)
    assert isinstance(guardrail_assignment.targets[0], ast.Name)
    assert guardrail_assignment.targets[0].id == "guardrail_result"

    guardrail_gate = invoke_scope_with.body[statement_indexes["evaluate_input_guardrail"] + 1]
    assert isinstance(guardrail_gate, ast.If)
    assert ast.unparse(guardrail_gate.test) == "not guardrail_result.allowed"
    assert _statement_contains_call(guardrail_gate, "context.send_activity")
    assert any(isinstance(node, ast.Return) for node in guardrail_gate.body)


def test_start_server_registers_payload_logging_after_configure():
    module = _parse_module("start_server.py")

    payload_logger_import = _find_imported_name(
        module,
        "utils.payload_logging_exporter",
        "register_guardrail_payload_logging",
    )
    assert payload_logger_import is not None

    start_server = _find_function(module, "start_server")
    configure_index = next(
        index
        for index, statement in enumerate(start_server.body)
        if _statement_contains_call(statement, "configure")
    )
    register_index = next(
        index
        for index, statement in enumerate(start_server.body)
        if _statement_contains_call(statement, "register_guardrail_payload_logging")
    )

    assert register_index == configure_index + 1
