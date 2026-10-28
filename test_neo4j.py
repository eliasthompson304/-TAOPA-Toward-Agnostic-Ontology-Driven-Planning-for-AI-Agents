"""Offline Neo4j tests. These never connect to a database or run the model."""

# Local regression checks, not a reproduction of any paper's experiments.
# Mock outputs verify program contracts; ontology accuracy, correction effort,
# and downstream reliability require separate evaluation (REPORT.md, section 10).

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import graph
import neo4j_client
import prototype
from test_graph import HERE, example_answers, scripted, vectors


class FakeNeo4jError(Exception):
    pass


class FakeDriverError(Exception):
    pass


class Neo4jTests(unittest.TestCase):
    def setUp(self):
        key = patch("openai_client.api_key", return_value="test-api-key")
        key.start()
        self.addCleanup(key.stop)
        self.foundation = graph.load_foundation(HERE / "foundation.json")
        self.driver = MagicMock()
        self.session = self.driver.session.return_value.__enter__.return_value
        self.transaction = MagicMock()
        self.session.execute_write.side_effect = lambda callback: callback(self.transaction)
        exceptions = SimpleNamespace(DriverError=FakeDriverError, Neo4jError=FakeNeo4jError)
        module = SimpleNamespace(GraphDatabase=SimpleNamespace(driver=MagicMock(return_value=self.driver)))
        self.modules = {"neo4j": module, "neo4j.exceptions": exceptions}

    def test_clear_deletes_all_nodes_before_inserting_foundation(self):
        with patch.dict("sys.modules", self.modules):
            neo4j_client.write_graph(self.driver, "prototype_db", self.foundation, "test_arithmetic", clear=True)
        self.driver.session.assert_called_once_with(database="prototype_db")
        self.assertIn("CREATE CONSTRAINT", self.session.run.call_args.args[0])
        calls = self.transaction.run.call_args_list
        self.assertEqual(calls[0].args, ("MATCH (n) DETACH DELETE n",))
        self.assertIn("UNWIND $classes", calls[1].args[0])
        self.assertEqual(calls[1].args[1]["classes"], self.foundation["classes"])
        self.assertEqual(self.session.execute_write.call_count, 1)

    def test_later_uploads_do_not_delete_nodes(self):
        with patch.dict("sys.modules", self.modules):
            neo4j_client.write_graph(self.driver, "prototype_db", self.foundation, "test_arithmetic")
        queries = [call.args[0] for call in self.transaction.run.call_args_list]
        self.assertFalse(any("DELETE" in query for query in queries))
        self.assertEqual(len(queries), 6)
        for predicate in graph.PREDICATES:
            self.assertTrue(any(f"[r:{predicate}]" in query for query in queries))

    def test_database_error_is_reported_and_queries_share_one_transaction(self):
        self.transaction.run.side_effect = [MagicMock(), FakeNeo4jError("Scripted failure")]
        with patch.dict("sys.modules", self.modules):
            with self.assertRaisesRegex(neo4j_client.DatabaseError, "data transaction was rolled back"):
                neo4j_client.write_graph(self.driver, "prototype_db", self.foundation, "test_arithmetic", clear=True)
        self.assertEqual(self.session.execute_write.call_count, 1)

    def test_connection_failure_closes_driver(self):
        self.driver.verify_connectivity.side_effect = FakeDriverError("Offline")
        with patch.dict("sys.modules", self.modules):
            with self.assertRaisesRegex(neo4j_client.DatabaseError, "Cannot connect"):
                neo4j_client.connect("neo4j://localhost:7687", "neo4j", "test-password")
        self.driver.close.assert_called_once()

    def test_run_resets_once_then_publishes_validated_documents(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            publish = MagicMock()
            file = HERE / "examples/manufacturing.txt"
            second = Path(directory) / "z_repeat.txt"
            second.write_text(file.read_text())
            repeat = example_answers()
            for index, item in enumerate(repeat[0]["classes"], start=1):
                repeat[index] = {"decision": "reuse", "class": item["name"],
                                 "same_meaning": True, "reason": "Same type"}
            self.assertTrue(prototype.run([second, file], directory, "test_publish", self.foundation, {},
                                          scripted(example_answers() + repeat), vectors, publish))
            self.assertEqual(publish.call_count, 3)
            self.assertEqual(publish.call_args_list[0].kwargs, {"clear": True})
            self.assertEqual(len(publish.call_args_list[0].args[0]["classes"]), 7)
            self.assertEqual(publish.call_args_list[1].kwargs, {})
            self.assertEqual(len(publish.call_args_list[1].args[0]["classes"]), 12)
            self.assertEqual(publish.call_args_list[2].kwargs, {})
            self.assertEqual(len(publish.call_args_list[2].args[0]["classes"]), 12)

    def test_invalid_edge_is_rejected_and_valid_work_is_uploaded(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            publish = MagicMock()
            answers = example_answers()
            answers[-1]["relationships"][0]["predicate"] = "worksNear"
            self.assertTrue(prototype.run([HERE / "examples/manufacturing.txt"], directory,
                                          "test_publish", self.foundation, {}, scripted(answers), vectors, publish))
            self.assertEqual(publish.call_count, 2)
            result = graph.read_json(Path(directory) / "graph.json")
            self.assertEqual(len(result["classes"]), 12)
            self.assertEqual(len(result["relationships"]), 15)
            self.assertFalse(any(edge["predicate"] == "worksNear" for edge in result["relationships"]))
            self.assertEqual(publish.call_args.args[0], result)

    def test_export_only_cli_never_connects_or_requests_a_password(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = ["prototype.py", "--domain", "arithmetic", "--export-only", "--output", directory,
                         str(HERE / "examples/arithmetic.txt")]
            with patch("sys.argv", arguments), patch("prototype.run", return_value=True) as run:
                with patch("neo4j_client.connect") as connect, patch("getpass.getpass") as password:
                    self.assertEqual(prototype.main(), 0)
            connect.assert_not_called()
            password.assert_not_called()
            self.assertIsNone(run.call_args.args[-1])

    def test_cli_uses_local_database_and_keeps_password_out_of_settings(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            arguments = ["prototype.py", "--domain", "arithmetic", "--output", directory,
                         str(HERE / "examples/arithmetic.txt")]

            def fake_run(*args):
                args[-1](self.foundation, "first_prototype_arithmetic", clear=True)
                return True

            with patch.dict(os.environ, {"NEO4J_PASSWORD": "test-password"}, clear=True):
                with patch("sys.argv", arguments), patch("prototype.run", side_effect=fake_run) as run:
                    with patch("neo4j_client.connect", return_value=self.driver) as connect:
                        with patch("neo4j_client.write_graph") as write:
                            self.assertEqual(prototype.main(), 0)
            connect.assert_called_once_with("neo4j://127.0.0.1:7687", "neo4j", "test-password")
            write.assert_called_once_with(self.driver, "neo4j", self.foundation, "first_prototype_arithmetic", True)
            self.assertNotIn("test-password", str(run.call_args.args[4]))
            self.assertNotIn("test-api-key", str(run.call_args.args[4]))
            self.assertEqual(run.call_args.args[4]["provider"], "openai")
            self.driver.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
