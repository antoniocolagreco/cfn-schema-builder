# cfn-schema

Builds a single draft-07 JSON Schema for validating CloudFormation templates, starting from the resource provider schemas published by AWS.

## Usage

Put the JSON files downloaded from AWS in `download/` (one per resource type, e.g. `aws-s3-bucket.json`) and run:

```sh
python3 build-schema.py
```

The output is `cfn-template.schema.json` (~8 MB, 1065 resource types plus custom resources), usable for template autocompletion and validation in the editor.

## What the script does

- Builds the template skeleton: `AWSTemplateFormatVersion`, `Parameters`, `Mappings`, `Conditions`, `Rules`, `Outputs`, `Transform`, `Metadata` and `Resources`.
- For each resource provider it generates a definition with `Type`, `Properties` and the `Condition`, `DependsOn`, `DeletionPolicy`, `UpdateReplacePolicy`, `CreationPolicy`, `UpdatePolicy`, `Metadata` attributes.
- Drops the properties listed in `readOnlyProperties`, since they cannot be written in a template.
- Makes `Properties` required only when the source schema declares required properties.
- Supports `Custom::<name>` resource types (for example `Custom::S3Objects`) and
  `AWS::CloudFormation::CustomResource`, requiring `ServiceToken` and allowing
  provider-defined fields in `Properties`. Standard resource attributes remain validated.
  See the [AWS custom resource reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cloudformation-customresource.html).
- Prefixes each resource's `definitions` with its `typeName`, so names don't collide in the merged schema.
- Resolves internal `resource-schema.json#/properties/...` references by inlining the target property, with cycle protection.
- Widens every scalar type to `anyOf: [scalar, array, object]`, so intrinsic functions (`Ref`, `Fn::GetAtt`, `Fn::Sub`, ...) and their YAML shorthands aren't reported as errors.

## Resource policies

The provider files in `download/` describe resource properties, not CloudFormation
template attributes. The builder supplies nested `CreationPolicy` and `UpdatePolicy`
schemas for the resource types that support them, including signal settings,
Auto Scaling updates and instance refresh, AppStream, ElastiCache, OpenSearch,
Elasticsearch and Lambda alias deployments. Unsupported resources do not offer these
attributes. Policy scalars use the same intrinsic-function relaxation as resource
properties. These schemas support completion and structural validation; they do not
implement every CloudFormation runtime constraint or cross-property dependency.

Sources: [CreationPolicy](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-creationpolicy.html)
and [UpdatePolicy](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-updatepolicy.html).

## Tests

```sh
python3 -m pip install -r requirements-test.txt
python3 -m unittest -v
```

Tests rebuild in a temporary directory, verify that the committed schema is current,
check draft-07 validity, and cover custom resources and policy completion keys and validation.
