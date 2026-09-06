#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).parent
SOURCE = ROOT / "download"
OUTPUT = ROOT / "cfn-template.schema.json"

SCALARS = {"string", "number", "integer", "boolean"}
CARRIED = ("description", "title")
SCHEMA_KEYS = ("properties", "definitions", "required", "additionalProperties",
               "oneOf", "anyOf", "allOf", "dependencies", "patternProperties")

PARAMETER_TYPES = [
    "String", "Number", "List<Number>", "CommaDelimitedList",
    "AWS::EC2::AvailabilityZone::Name", "AWS::EC2::Image::Id",
    "AWS::EC2::Instance::Id", "AWS::EC2::KeyPair::KeyName",
    "AWS::EC2::SecurityGroup::GroupName", "AWS::EC2::SecurityGroup::Id",
    "AWS::EC2::Subnet::Id", "AWS::EC2::Volume::Id", "AWS::EC2::VPC::Id",
    "AWS::Route53::HostedZone::Id",
    "List<AWS::EC2::AvailabilityZone::Name>", "List<AWS::EC2::Image::Id>",
    "List<AWS::EC2::Instance::Id>", "List<AWS::EC2::SecurityGroup::Id>",
    "List<AWS::EC2::Subnet::Id>", "List<AWS::EC2::VPC::Id>",
    "List<AWS::Route53::HostedZone::Id>",
    "AWS::SSM::Parameter::Name", "AWS::SSM::Parameter::Value<String>",
    "AWS::SSM::Parameter::Value<List<String>>",
    "AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>",
    "AWS::SSM::Parameter::Value<AWS::EC2::KeyPair::KeyName>",
    "AWS::SSM::Parameter::Value<AWS::EC2::SecurityGroup::Id>",
    "AWS::SSM::Parameter::Value<AWS::EC2::Subnet::Id>",
    "AWS::SSM::Parameter::Value<AWS::EC2::VPC::Id>",
]

DELETION_POLICIES = ["Delete", "Retain", "RetainExceptOnCreate", "Snapshot"]


SELF_REF_PREFIXES = ("resource-schema.json#/properties/", "#/properties/")


def self_ref_target(value):
    for prefix in SELF_REF_PREFIXES:
        if isinstance(value, str) and value.startswith(prefix):
            return value[len(prefix):]
    return None


def inline_self_refs(node, root_properties, seen=()):
    if isinstance(node, list):
        return [inline_self_refs(item, root_properties, seen) for item in node]
    if not isinstance(node, dict):
        return node
    target = self_ref_target(node.get("$ref"))
    if target is not None:
        if target in seen or target not in root_properties:
            return {}
        resolved = inline_self_refs(root_properties[target], root_properties, seen + (target,))
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        return {**resolved, **siblings}
    return {key: inline_self_refs(value, root_properties, seen) for key, value in node.items()}


def namespaced(type_name, node):
    if isinstance(node, list):
        return [namespaced(type_name, item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key == "$ref" and isinstance(value, str) and value.startswith("#/definitions/"):
            result[key] = f"#/definitions/{type_name}.{value[len('#/definitions/'):]}"
        else:
            result[key] = namespaced(type_name, value)
    return result


def relax(node):
    if isinstance(node, list):
        return [relax(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: relax(value) for key, value in node.items()}
    node_type = node.get("type")
    if not (isinstance(node_type, str) and node_type in SCALARS):
        return node
    carried = {key: node.pop(key) for key in CARRIED if key in node}
    return {**carried, "anyOf": [node, {"type": "array"}, {"type": "object"}]}


def top_level_read_only(schema):
    prefix = "/properties/"
    return {pointer[len(prefix):] for pointer in schema.get("readOnlyProperties", [])
            if pointer.startswith(prefix) and "/" not in pointer[len(prefix):]}


def policy_object(properties, description, required=()):
    result = {"type": "object", "properties": properties,
              "additionalProperties": False, "description": description}
    if required:
        result["required"] = list(required)
    return result


def resource_policies(type_name):
    # Resource provider schemas describe Properties, not template attributes.
    # Sources: AWS TemplateReference/aws-attribute-{creationpolicy,updatepolicy}.html
    boolean = {"type": "boolean"}
    integer = {"type": "integer"}
    string = {"type": "string"}
    percentage = {"type": "integer", "minimum": 0, "maximum": 100}
    signal = policy_object({
        "Count": {"type": "integer", "minimum": 1,
                  "description": "Number of success signals required (default: 1)."},
        "Timeout": {"type": "string",
                    "description": "Signal timeout as an ISO 8601 duration, up to PT12H (default: PT5M)."},
    }, "Wait for resource success signals before completing creation.")
    creation, update = {}, {}
    if type_name in ("AWS::EC2::Instance", "AWS::CloudFormation::WaitCondition",
                     "AWS::AutoScaling::AutoScalingGroup"):
        creation["ResourceSignal"] = signal
    if type_name == "AWS::AppStream::Fleet":
        creation["StartFleet"] = boolean
        update = {"StopBeforeUpdate": boolean, "StartAfterUpdate": boolean}
    if type_name == "AWS::AutoScaling::AutoScalingGroup":
        creation["AutoScalingCreationPolicy"] = policy_object({
            "MinSuccessfulInstancesPercent": percentage,
        }, "Percentage of instances that must signal successful creation.")
        update = {
            "AutoScalingReplacingUpdate": policy_object({"WillReplace": boolean},
                "Replace the Auto Scaling group and its instances."),
            "AutoScalingRollingUpdate": policy_object({
                "MaxBatchSize": {"type": "integer", "minimum": 1, "maximum": 100},
                "MinInstancesInService": {"type": "integer", "minimum": 0},
                "MinSuccessfulInstancesPercent": percentage,
                "PauseTime": {"type": "string", "description": "Pause duration in ISO 8601 format, up to PT1H."},
                "SuspendProcesses": {"type": "array", "items": string},
                "WaitOnResourceSignals": boolean,
            }, "Update instances in batches."),
            "AutoScalingScheduledAction": policy_object({
                "IgnoreUnmodifiedGroupSizeProperties": boolean,
            }, "Preserve group sizes changed by scheduled actions."),
            "AutoScalingInstanceRefresh": policy_object({
                "Strategy": {"type": "string", "enum": ["Rolling", "ReplaceRootVolume"]},
                "Preferences": policy_object({
                    "AlarmSpecification": policy_object({
                        "Alarms": {"type": "array", "items": string, "maxItems": 10},
                    }, "CloudWatch alarms to monitor during the refresh."),
                    "BakeTime": {"type": "integer", "minimum": 0, "maximum": 172800},
                    "CheckpointDelay": {"type": "integer", "minimum": 0, "maximum": 172800},
                    "CheckpointPercentages": {"type": "array", "items": percentage},
                    "InstanceWarmup": integer,
                    "MaxHealthyPercentage": {"type": "integer", "minimum": 100, "maximum": 200},
                    "MinHealthyPercentage": percentage,
                    "ScaleInProtectedInstances": {"type": "string", "enum": ["Refresh", "Ignore", "Wait"]},
                    "SkipMatching": boolean,
                    "StandbyInstances": {"type": "string", "enum": ["Terminate", "Ignore", "Wait"]},
                }, "Instance refresh preferences."),
            }, "Refresh instances using Auto Scaling.", required=("Strategy",)),
        }
    if type_name == "AWS::ElastiCache::ReplicationGroup":
        update["UseOnlineResharding"] = boolean
    if type_name in ("AWS::OpenSearchService::Domain", "AWS::Elasticsearch::Domain"):
        update["EnableVersionUpgrade"] = boolean
    if type_name == "AWS::Lambda::Alias":
        update["CodeDeployLambdaAliasUpdate"] = policy_object({
            "ApplicationName": string, "DeploymentGroupName": string,
            "BeforeAllowTrafficHook": string, "AfterAllowTrafficHook": string,
        }, "Deploy alias updates through CodeDeploy.",
            required=("ApplicationName", "DeploymentGroupName"))
    return {name: relax(policy_object(properties, description))
            for name, properties, description in (
                ("CreationPolicy", creation, "Control resource creation and success signals."),
                ("UpdatePolicy", update, "Control how CloudFormation updates this resource."),
            ) if properties}


def build_resource(schema):
    type_name = schema["typeName"]
    read_only = top_level_read_only(schema)

    properties = {name: value for name, value in schema["properties"].items()
                  if name not in read_only}

    body = {"type": "object", "properties": properties,
            "additionalProperties": schema.get("additionalProperties", False)}
    for key in SCHEMA_KEYS:
        if key in schema and key not in ("properties", "definitions", "additionalProperties"):
            body[key] = schema[key]
    if schema.get("description"):
        body["description"] = schema["description"]

    root = schema["properties"]
    body = relax(namespaced(type_name, inline_self_refs(body, root)))
    definitions = {f"{type_name}.{name}": relax(namespaced(type_name, inline_self_refs(value, root)))
                   for name, value in schema.get("definitions", {}).items()}

    resource = {
        "type": "object",
        "additionalProperties": False,
        "required": ["Type"],
        "properties": {
            "Type": {"type": "string", "enum": [type_name],
                     "description": schema.get("description", "")},
            "Properties": body,
            "Condition": {"type": "string"},
            "DependsOn": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "DeletionPolicy": {"type": "string", "enum": DELETION_POLICIES},
            "UpdateReplacePolicy": {"type": "string", "enum": DELETION_POLICIES},
            **resource_policies(type_name),
            "Metadata": {"type": "object"},
        },
    }
    if schema.get("required"):
        resource["required"].append("Properties")
    if schema.get("description"):
        resource["description"] = schema["description"]
    return resource, definitions


definitions = {}
resource_refs = []

for path in sorted(SOURCE.glob("*.json")):
    schema = json.loads(path.read_text())
    resource, nested = build_resource(schema)
    definitions[schema["typeName"]] = resource
    definitions.update(nested)
    resource_refs.append({"$ref": f"#/definitions/{schema['typeName']}"})

template = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["Resources"],
    "properties": {
        "AWSTemplateFormatVersion": {"type": "string", "enum": ["2010-09-09"]},
        "Description": {"type": "string", "maxLength": 1024},
        "Transform": {"anyOf": [{"type": "string"}, {"type": "array"}, {"type": "object"}]},
        "Metadata": {"type": "object"},
        "Mappings": {"type": "object", "additionalProperties": {"type": "object"}},
        "Conditions": {"type": "object", "additionalProperties": {"type": "object"}},
        "Rules": {"type": "object", "additionalProperties": {"type": "object"}},
        "Parameters": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["Type"],
                "properties": {
                    "Type": {"type": "string", "enum": PARAMETER_TYPES},
                    "Description": {"type": "string", "maxLength": 4000},
                    "Default": {},
                    "AllowedValues": {"type": "array"},
                    "AllowedPattern": {"type": "string"},
                    "ConstraintDescription": {"type": "string"},
                    "MaxLength": {"type": "integer"},
                    "MinLength": {"type": "integer"},
                    "MaxValue": {"type": "number"},
                    "MinValue": {"type": "number"},
                    "NoEcho": {"type": "boolean"},
                },
            },
        },
        "Outputs": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["Value"],
                "properties": {
                    "Value": {},
                    "Description": {"type": "string", "maxLength": 1024},
                    "Condition": {"type": "string"},
                    "Export": {"type": "object", "properties": {"Name": {}},
                               "required": ["Name"], "additionalProperties": False},
                },
            },
        },
        "Resources": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": False,
            "patternProperties": {"^[a-zA-Z0-9]+$": {"anyOf": resource_refs}},
        },
    },
    "definitions": definitions,
}

OUTPUT.write_text(json.dumps(template))
print(f"{OUTPUT.name}: {len(resource_refs)} risorse, {len(definitions)} definizioni, "
      f"{OUTPUT.stat().st_size / 1_000_000:.1f} MB")
