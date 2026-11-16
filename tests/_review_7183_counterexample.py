"""The Spec router may select a tool the request policy has withheld."""

import json
import sys
import types
from dataclasses import replace

import pytest

from src import agent_loop
from src.tool_policy import ToolPolicy
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
from src.turn_contract import resolve_turn_contract


PROMPT = "open twitter and see what elon tweeted last"


@pytest.fixture(autouse=True)
def isolate_active_contract():
    from src.turn_contract import _ACTIVE_CONTRACT
    token = _ACTIVE_CONTRACT.set(None)
    yield
    _ACTIVE_CONTRACT.reset(token)

import pytest
from tests.test_spec_route_policy_conflict import *  # noqa


@pytest.mark.parametrize("prompt", [
    "Draft a reply to this email:\n> Hi Kevin, could you check the messages I sent last week and confirm?",
    "Don't search my emails, just draft a reply saying thanks.",
    "Write a reply to Ana; tell her I will look through the inbox tomorrow.",
])
def test_review_draft_only_prompt_stays_narrow(monkeypatch, prompt):
    schemas = [
        {"type": "function", "function": {
            "name": name, "description": name,
            "parameters": {"type": "object", "properties": {}},
        }}
        for name in (
            "mcp__email__draft_email",
            "mcp__email__search_emails",
            "mcp__email__read_email",
        )
    ]

    class FakeMCPManager:
        def get_all_openai_schemas(self, disabled):
            return schemas

    fake = types.ModuleType("src.spec_router")
    fake.LAST_DECISIONS = [{
        "choice": "t10",
        "top": [("draft_email", 0.468), ("search_emails", 0.082)],
    }]
    fake.latest_decision = lambda: fake.LAST_DECISIONS[-1]
    fake.spec_route_tools = lambda *a, **kw: ({"draft_email"}, True)
    monkeypatch.setitem(sys.modules, "src.spec_router", fake)
    monkeypatch.setattr(agent_loop, "_configured_model_tool_surface_raw", lambda *a, **kw: "spec")
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: FakeMCPManager())
    monkeypatch.setenv("ODYSSEUS_SPEC_MODE", "strict")
    monkeypatch.setenv("ODYSSEUS_SPEC_SUBSET_OF_BASE", "1")

    policy = ToolPolicy()
    contract = resolve_turn_contract(
        capabilities={"email"}, required_capabilities=set(),
        schemas=schemas, policy=policy,
        selected_tools={
            "mcp__email__draft_email",
            "mcp__email__search_emails",
            "mcp__email__read_email",
        },
        message=prompt,
    )
    assert "mcp__email__search_emails" in contract.offered
    assert "mcp__email__read_email" in contract.offered

    routed = agent_loop._spec_router_contract(
        contract, [{"role": "user", "content": prompt}],
        set(), "http://fixture", "Ajax", "fixture", {},
        tool_policy=policy,
    )
    print("OFFERED", sorted(routed.offered))
    assert "mcp__email__search_emails" not in routed.offered
