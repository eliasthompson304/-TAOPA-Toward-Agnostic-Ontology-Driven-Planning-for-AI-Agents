"""Offline reset checks: never connect to a database or call a model."""

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import os
import unittest
from unittest.mock import MagicMock, patch

import reset_foundation


class ResetTests(unittest.TestCase):
    def invoke(self, domain, write_error=None):
        driver = MagicMock()
        with patch.dict(os.environ, {"NEO4J_PASSWORD": "test-password"}), \
                patch("sys.argv", ["reset_foundation.py", "--domain", domain]), \
                patch.object(reset_foundation.neo4j_client, "connect", return_value=driver) as connect, \
                patch.object(reset_foundation.neo4j_client, "write_graph", side_effect=write_error) as write, \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = reset_foundation.main()
        return code, driver, connect, write

    def test_reset_writes_only_validated_foundation_and_closes_driver(self):
        code, driver, connect, write = self.invoke("arithmetic")
        self.assertEqual(code, 0)
        connect.assert_called_once()
        args = write.call_args.args
        self.assertIs(args[0], driver)
        self.assertEqual(args[3], "first_prototype_arithmetic")
        self.assertEqual(write.call_args.kwargs, {"clear": True})
        foundation = args[2]
        self.assertEqual(len(foundation["classes"]), 7)
        self.assertTrue(all(item["foundation"] for item in foundation["classes"]))
        self.assertEqual(len(foundation["relationships"]), 7)
        self.assertEqual({edge["predicate"] for edge in foundation["relationships"] if edge["predicate"] == "subClassOf"}, {"subClassOf", "performs"})
        self.assertIn({"source": "Agent", "predicate": "performs", "target": "Action",
                       "source_file": None, "evidence": None}, foundation["relationships"])
        parents = {edge["source"]: edge["target"] for edge in foundation["relationships"] if edge["predicate"] == "subClassOf"}
        self.assertNotIn("Thing", parents)
        self.assertEqual(parents["Entity"], "Thing")
        self.assertEqual(parents["Action"], "Thing")
        self.assertEqual(parents["Value"], "Entity")
        driver.close.assert_called_once()

    def test_invalid_domain_stops_before_database_access(self):
        code, driver, connect, write = self.invoke("bad-domain")
        self.assertEqual(code, 1)
        connect.assert_not_called()
        write.assert_not_called()

    def test_database_failure_returns_failure_and_closes_driver(self):
        code, driver, connect, write = self.invoke(
            "arithmetic", reset_foundation.neo4j_client.DatabaseError("Mock failure"))
        self.assertEqual(code, 1)
        driver.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
