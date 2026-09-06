import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft7Validator


ROOT = Path(__file__).parent


class PolicySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            shutil.copy2(ROOT / "build-schema.py", work)
            (work / "download").symlink_to(ROOT / "download", target_is_directory=True)
            subprocess.run([sys.executable, str(work / "build-schema.py")], check=True)
            cls.generated = (work / "cfn-template.schema.json").read_bytes()
        cls.schema = json.loads(cls.generated)

    def policy(self, resource, name):
        return self.schema["definitions"][resource]["properties"][name]

    def test_generated_schema_is_current_and_valid(self):
        self.assertEqual(self.generated, (ROOT / "cfn-template.schema.json").read_bytes())
        # AWS patterns include Unicode escapes unsupported by Python's re engine.
        # Check schema structure without treating those patterns as Python regexes.
        Draft7Validator.check_schema(self.schema, format_checker=None)

    def test_creation_completion_properties(self):
        creation = self.policy("AWS::AutoScaling::AutoScalingGroup", "CreationPolicy")
        self.assertEqual(set(creation["properties"]), {"ResourceSignal", "AutoScalingCreationPolicy"})
        self.assertEqual(set(creation["properties"]["ResourceSignal"]["properties"]), {"Count", "Timeout"})
        self.assertIn("MinSuccessfulInstancesPercent", creation["properties"]["AutoScalingCreationPolicy"]["properties"])

    def test_creation_validation_and_intrinsics(self):
        validator = Draft7Validator(self.policy("AWS::EC2::Instance", "CreationPolicy"))
        for value in ({"ResourceSignal": {"Count": 2, "Timeout": "PT15M"}},
                      {"ResourceSignal": {"Count": {"Ref": "SignalCount"}}}):
            with self.subTest(value=value):
                self.assertTrue(validator.is_valid(value))
        for value in ({"ResourceSignal": {"Cont": 2}},
                      {"ResourceSignal": {"Count": 0}},
                      {"ResourceSignal": {"Count": "invalid"}},
                      {"ResourceSignal": "invalid"}):
            with self.subTest(value=value):
                self.assertFalse(validator.is_valid(value))

    def test_resource_specific_policies(self):
        for resource in ("AWS::EC2::Instance", "AWS::CloudFormation::WaitCondition"):
            self.assertEqual(set(self.policy(resource, "CreationPolicy")["properties"]), {"ResourceSignal"})
        self.assertEqual(set(self.policy("AWS::AppStream::Fleet", "CreationPolicy")["properties"]), {"StartFleet"})
        for name in ("CreationPolicy", "UpdatePolicy"):
            self.assertNotIn(name, self.schema["definitions"]["AWS::S3::Bucket"]["properties"])

    def test_update_completion_and_validation(self):
        update = self.policy("AWS::AutoScaling::AutoScalingGroup", "UpdatePolicy")
        self.assertEqual(set(update["properties"]), {
            "AutoScalingReplacingUpdate", "AutoScalingRollingUpdate",
            "AutoScalingScheduledAction", "AutoScalingInstanceRefresh"})
        validator = Draft7Validator(update)
        self.assertTrue(validator.is_valid({"AutoScalingRollingUpdate": {
            "MaxBatchSize": 2, "WaitOnResourceSignals": True, "PauseTime": "PT5M",
            "SuspendProcesses": ["HealthCheck"]}}))
        self.assertFalse(validator.is_valid({"AutoScalingRollingUpdate": {"MaxBatchSize": 0}}))
        self.assertTrue(validator.is_valid({"AutoScalingInstanceRefresh": {
            "Strategy": "Rolling", "Preferences": {"AlarmSpecification": {"Alarms": ["Health"]}}}}))
        self.assertFalse(validator.is_valid({"AutoScalingInstanceRefresh": {"Strategy": "invalid"}}))

    def test_other_update_policies(self):
        expected = {
            "AWS::AppStream::Fleet": {"StopBeforeUpdate", "StartAfterUpdate"},
            "AWS::ElastiCache::ReplicationGroup": {"UseOnlineResharding"},
            "AWS::OpenSearchService::Domain": {"EnableVersionUpgrade"},
            "AWS::Elasticsearch::Domain": {"EnableVersionUpgrade"},
            "AWS::Lambda::Alias": {"CodeDeployLambdaAliasUpdate"},
        }
        for resource, properties in expected.items():
            with self.subTest(resource=resource):
                self.assertEqual(set(self.policy(resource, "UpdatePolicy")["properties"]), properties)
        validator = Draft7Validator(self.policy("AWS::Lambda::Alias", "UpdatePolicy"))
        self.assertTrue(validator.is_valid({"CodeDeployLambdaAliasUpdate": {
            "ApplicationName": {"Ref": "Application"}, "DeploymentGroupName": "Group"}}))
        self.assertFalse(validator.is_valid({"CodeDeployLambdaAliasUpdate": {}}))


if __name__ == "__main__":
    unittest.main()
