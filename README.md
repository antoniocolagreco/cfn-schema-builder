# cfn-schema

Builds a single draft-07 JSON Schema for validating CloudFormation templates, starting from the resource provider schemas published by AWS.

## Usage

Put the JSON files downloaded from AWS in `download/` (one per resource type, e.g. `aws-s3-bucket.json`) and run:

```sh
python3 build-schema.py
```

The output is `cfn-template.schema.json` (~8 MB, 1065 resources), usable for template autocompletion and validation in the editor.

## What the script does

- Builds the template skeleton: `AWSTemplateFormatVersion`, `Parameters`, `Mappings`, `Conditions`, `Rules`, `Outputs`, `Transform`, `Metadata` and `Resources`.
- For each resource provider it generates a definition with `Type`, `Properties` and the `Condition`, `DependsOn`, `DeletionPolicy`, `UpdateReplacePolicy`, `CreationPolicy`, `UpdatePolicy`, `Metadata` attributes.
- Drops the properties listed in `readOnlyProperties`, since they cannot be written in a template.
- Makes `Properties` required only when the source schema declares required properties.
- Prefixes each resource's `definitions` with its `typeName`, so names don't collide in the merged schema.
- Resolves internal `resource-schema.json#/properties/...` references by inlining the target property, with cycle protection.
- Widens every scalar type to `anyOf: [scalar, array, object]`, so intrinsic functions (`Ref`, `Fn::GetAtt`, `Fn::Sub`, ...) and their YAML shorthands aren't reported as errors.
