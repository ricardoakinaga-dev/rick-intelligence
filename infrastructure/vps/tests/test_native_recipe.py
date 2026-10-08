"""Real BuildKit metadata shape; simulated remote authority is unit evidence only."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
import construction_contract as cc
from contracts import Refusal
from test_safety import construction_fixture, construction_review, SOURCE


def native_shape():
    native = json.loads((Path(__file__).parent / "fixtures/buildkit-native-recipe-v02.json").read_text())
    policy, _, _ = construction_fixture()
    recipe, mapping = native["buildConfig"], native["source"]
    # Context/material authority comes from a TEST ONLY fixture. This exercises
    # the actual native recipe/map format, never approval of the local build.
    policy["build_config_sha256"] = cc.canonical_sha256(recipe)
    policy["source_mapping_sha256"] = cc.canonical_sha256(mapping)
    policy["dockerfile_source_name"] = mapping["infos"][0]["filename"]
    policy["dockerfile_sha256"] = hashlib.sha256(base64.b64decode(mapping["infos"][0]["data"])).hexdigest()
    predicate = {"invocation": {"configSource": policy["context"], "parameters": policy["parameters"]},
                 "materials": policy["materials"], "buildConfig": recipe,
                 "metadata": {"completeness": {"parameters": True, "materials": True}, cc.META: {"source": mapping}}}
    return policy, predicate


def test_actual_native_recipe_sink_and_wrapped_locations_are_valid_shapes():
    policy, predicate = native_shape()
    assert predicate["buildConfig"]["llbDefinition"][-1]["op"]["Op"] == {}
    assert isinstance(next(iter(predicate["metadata"][cc.META]["source"]["locations"].values())), dict)
    assert cc.verify_recipe(predicate, policy)["dockerfile_sha256"] == policy["dockerfile_sha256"]


@pytest.mark.parametrize("part", ["buildConfig", "source"])
def test_actual_native_shape_still_requires_exact_reviewed_hash(part):
    policy, predicate = native_shape()
    predicate = copy.deepcopy(predicate)
    if part == "buildConfig":
        predicate[part]["llbDefinition"][-1]["inputs"] = ["step0:0"]
    else:
        predicate["metadata"][cc.META][part]["locations"]["step0"]["locations"][0]["ranges"][0]["start"]["line"] = 999
    with pytest.raises(Refusal):
        cc.verify_recipe(predicate, policy)


def native_parameter_policy():
    data, _, dockerfile = construction_review()
    policy = json.loads(data)
    parameters = policy["parameters"]
    parameters.pop("secrets")
    parameters.pop("ssh")
    parameters["compatibilityVersion"] = 30
    parameters["root"] = {"configSource": {"path": "api.Dockerfile"},
                          "request": {"args": dict(parameters["args"])}}
    return policy, dockerfile


def test_native_gateway_root_and_omitted_empty_secret_fields_are_valid():
    policy, dockerfile = native_parameter_policy()
    data = json.dumps(policy).encode()
    assert cc.admit_review(data, hashlib.sha256(data).hexdigest(), dockerfile,
                           service="api", source=SOURCE) == policy


@pytest.mark.parametrize("field", ["locals", "secrets", "ssh"])
@pytest.mark.parametrize("depth", [1, 2])
def test_native_gateway_root_cannot_hide_nonremote_inputs(field, depth):
    policy, dockerfile = native_parameter_policy()
    request = policy["parameters"]["root"]["request"]
    if depth == 2:
        request["root"] = {"request": {}}
        request = request["root"]["request"]
    request[field] = [{"id": "TEST ONLY forbidden"}]
    data = json.dumps(policy).encode()
    with pytest.raises(Refusal):
        cc.admit_review(data, hashlib.sha256(data).hexdigest(), dockerfile,
                        service="api", source=SOURCE)
