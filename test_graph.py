"""Offline tests. Scripted responses test plumbing, not the model's ontology quality."""

# Local regression checks, not a reproduction of any paper's experiments.
# Mock outputs verify program contracts; ontology accuracy, correction effort,
# and downstream reliability require separate evaluation (REPORT.md, section 10).

from collections import deque
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import graph
import openai_client
import prototype
import prompts


HERE = Path(__file__).resolve().parent


def vectors(texts):
    # A small, predictable stand-in for embeddings. Never calls the API.
    return [[1.0, 0.5, 0.25] for text in texts]


def example_answers(domain="manufacturing"):
    if domain == "manufacturing":
        rows = [
            ("QualityInspector", "Agent"),
            ("EquipmentInspection", "Action"),
            ("InspectionReport", "InformationObject"),
            ("Equipment", "PhysicalObject"),
            ("InspectionChecklist", "InformationObject"),
        ]
    else:
        rows = [
            ("Recruiter", "Agent"),
            ("CandidateScreening", "Action"),
            ("ScreeningReport", "InformationObject"),
            ("JobDescription", "InformationObject"),
            ("CandidateApplication", "InformationObject"),
        ]
    classes = []
    placements = []
    for index, (name, parent) in enumerate(rows, start=1):
        classes.append({"id": f"c{index}", "name": name,
                        "description": f"A workplace {name} type.",
                        "sentence_id": "s1" if index <= 2 else "s2"})
        placements.append({"decision": "new", "parent": parent, "reason": "Scripted test placement"})
    relations = [
        {"source": "c1", "phrase": "conduct", "target": "c2", "sentence_id": "s1"},
        {"source": "c2", "phrase": "produce", "target": "c3", "sentence_id": "s2"},
        {"source": "c2", "phrase": "require", "target": "c4", "sentence_id": "s2"},
        {"source": "c2", "phrase": "accept", "target": "c5", "sentence_id": "s2"},
    ]
    mappings = []
    for index, label in enumerate(["performs", "produces", "dependsOn", "acceptsParam"], start=1):
        mappings.append({"id": f"r{index}", "predicate": label, "reason": "Scripted test mapping"})
    return [{"classes": classes, "relationships": relations}] + placements + [{"relationships": mappings}]


def scripted(answers):
    pending = deque(deepcopy(answers))

    def ask(messages):
        if not pending:
            raise AssertionError("Unexpected model call")
        return pending.popleft()

    return ask


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.foundation = graph.load_foundation(HERE / "foundation.json")
        self.text = (HERE / "examples/manufacturing.txt").read_text()
        self.sources = {"sample.txt": self.text}
        self.good = prototype.process_document(
            self.text, "sample.txt", self.foundation, self.foundation, {},
            scripted(example_answers()), vectors,
        )

    def rejects(self, changed, message):
        with self.assertRaisesRegex(graph.ValidationError, message):
            graph.validate(changed, self.foundation, self.sources)

    def test_thing_is_the_only_root_above_entity_and_action(self):
        expected = {
            'Thing': None, 'Entity': 'Thing', 'Action': 'Thing',
            'Value': 'Entity', 'InformationObject': 'Entity',
            'PhysicalObject': 'Entity', 'Agent': 'Entity',
        }
        self.assertEqual(graph.PARENTS, expected)
        parents = {edge['source']: edge['target'] for edge in self.foundation['relationships'] if edge['predicate'] == 'subClassOf'}
        self.assertEqual(parents, {name: parent for name, parent in expected.items() if parent})
        for name in expected:
            self.assertIn('Thing', graph.ancestors(self.foundation, name))
        self.assertNotIn('Entity', graph.ancestors(self.foundation, 'Action'))
        graph.validate(self.foundation, self.foundation, {})

    def test_direct_entity_subclass_and_entity_output_are_valid(self):
        changed = deepcopy(self.good)
        graph.add_class(changed, {'name': 'Resource', 'description': 'A non-action resource.',
                                 'evidence': 'equipment'}, 'Entity', 'sample.txt')
        graph.add_relationship(changed, {
            'source': 'EquipmentInspection', 'predicate': 'produces', 'target': 'Entity',
            'source_file': 'sample.txt', 'evidence': 'inspection reports',
        })
        graph.validate(changed, self.foundation, self.sources)


    def test_valid_graph_uses_exact_five_predicates(self):
        graph.validate(self.good, self.foundation, self.sources)
        self.assertEqual(len(self.good["classes"]), 12)
        self.assertEqual(len(self.good["relationships"]), 16)
        self.assertEqual({edge["predicate"] for edge in self.good["relationships"]}, set(graph.PREDICATES))
        self.assertEqual(len(self.foundation["classes"]), 7)

    def test_old_and_unknown_predicates_fail(self):
        for label in ["precedes", "performsAction", "acceptsAsParam", "worksNear"]:
            with self.subTest(label=label):
                changed = deepcopy(self.good)
                changed["relationships"][-1]["predicate"] = label
                self.rejects(changed, "Unknown predicate")

    def test_unknown_endpoint_fails(self):
        changed = deepcopy(self.good)
        changed["relationships"][-1]["target"] = "Missing"
        self.rejects(changed, "Unknown relationship endpoint")

    def test_protected_definition_and_flag_fail(self):
        for field, value in [("description", "Changed"), ("foundation", False)]:
            with self.subTest(field=field):
                changed = deepcopy(self.good)
                changed["classes"][0][field] = value
                self.rejects(changed, "foundation")

    def test_protected_parent_change_and_removal_fail(self):
        changed = deepcopy(self.good)
        changed["relationships"][0]["target"] = "Action"
        self.rejects(changed, "source|foundation")
        changed = deepcopy(self.good)
        changed["relationships"].pop(0)
        self.rejects(changed, "Missing foundation edge")

    def test_invalid_foundation_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "foundation.json"
            changed = deepcopy(self.foundation)
            changed["relationships"][0]["target"] = "Action"
            graph.write_json(path, changed)
            with self.assertRaisesRegex(graph.ValidationError, "Foundation relationships"):
                graph.load_foundation(path)

    def test_cycle_fails(self):
        changed = deepcopy(self.good)
        edge = next(edge for edge in changed["relationships"] if edge["source"] == "Equipment")
        edge["target"] = "Equipment"
        self.rejects(changed, "cycle")

    def test_disjointness_and_multiple_parents_fail(self):
        changed = deepcopy(self.good)
        changed["relationships"].append({"source": "Equipment", "predicate": "subClassOf", "target": "Action",
                                          "source_file": "sample.txt", "evidence": "equipment"})
        self.rejects(changed, "disjoint")
        changed["relationships"][-1]["target"] = "InformationObject"
        self.rejects(changed, "1 parent")

    def test_new_class_cannot_attach_to_thing(self):
        changed = deepcopy(self.good)
        next(edge for edge in changed["relationships"] if edge["source"] == "Equipment")["target"] = "Thing"
        self.rejects(changed, "Entity or Action")

    def test_disconnected_class_fails(self):
        changed = deepcopy(self.good)
        changed["relationships"] = [edge for edge in changed["relationships"]
                                    if not (edge["source"] == "Equipment" and edge["predicate"] == "subClassOf")]
        self.rejects(changed, "1 parent")

    def test_wrong_domain_types_fail(self):
        for label, source, target in [
            ("performs", "Equipment", "EquipmentInspection"),
            ("produces", "EquipmentInspection", "Action"),
            ("acceptsParam", "QualityInspector", "Equipment"),
            ("dependsOn", "EquipmentInspection", "Thing"),
        ]:
            with self.subTest(label=label):
                changed = deepcopy(self.good)
                changed["relationships"][-1].update(predicate=label, source=source, target=target)
                self.rejects(changed, "Wrong source or target")

    def test_bad_evidence_fails(self):
        changed = deepcopy(self.good)
        changed["classes"][-1]["evidence"] = "A made-up sentence"
        self.rejects(changed, "source quote")

    def test_duplicates_keep_first_evidence(self):
        changed = deepcopy(self.good)
        duplicate = deepcopy(changed["relationships"][-1])
        duplicate["evidence"] = "inspection checklists"
        changed["relationships"].append(duplicate)
        graph.validate(changed, self.foundation, self.sources)
        self.assertEqual(changed, self.good)

    def test_existing_definition_and_parent_cannot_change(self):
        changed = deepcopy(self.good)
        changed["classes"][-1]["description"] = "New definition"
        with self.assertRaisesRegex(graph.ValidationError, "Existing class"):
            graph.validate(changed, self.foundation, self.sources, previous=self.good)
        changed = deepcopy(self.good)
        next(edge for edge in changed["relationships"] if edge["source"] == "InspectionReport")["target"] = "Value"
        with self.assertRaisesRegex(graph.ValidationError, "Existing relationship|Existing class parent"):
            graph.validate(changed, self.foundation, self.sources, previous=self.good)

    def test_cypher_has_only_fixed_labels_and_parameter_values(self):
        changed = deepcopy(self.good)
        evidence = 'Quote: "hello"\nMERGE (danger)'
        changed["classes"][-1]["description"] = evidence
        query, params = graph.cypher_export(changed, "test_manufacturing")
        self.assertNotIn(evidence, query)
        self.assertEqual(json.loads(json.dumps(params))["classes"][-1]["description"], evidence)
        self.assertEqual(set(params) - {"ontology", "classes"}, set(graph.PREDICATES))
        for label in graph.PREDICATES:
            self.assertIn(f"[r:{label}]", query)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.foundation = graph.load_foundation(HERE / "foundation.json")

    def test_two_domains_offline_and_reuse(self):
        for domain in ["manufacturing", "hr"]:
            with self.subTest(domain=domain), tempfile.TemporaryDirectory() as directory:
                file = HERE / "examples" / f"{domain}.txt"
                with patch("sys.stdout", new=StringIO()):
                    ok = prototype.run([file], directory, "test_" + domain, self.foundation,
                                       {"model": "scripted-test"}, scripted(example_answers(domain)), vectors)
                self.assertTrue(ok)
                output = Path(directory)
                self.assertEqual(len(graph.read_json(output / "graph.json")["classes"]), 12)
                self.assertEqual(graph.read_json(output / "decisions.json")["documents"][0]["status"], "accepted")
                self.assertTrue((output / "schema.cypher").exists())
                with patch("sys.stdout", new=StringIO()):
                    self.assertTrue(prototype.run([file], directory, "test_" + domain, self.foundation,
                                                  {}, scripted(example_answers(domain)), vectors))
                self.assertEqual(len(graph.read_json(output / "decisions.json")["documents"]), 1)

        candidates = {"classes": [{"id": "c1", "name": "Inspection", "description": "An action.",
                                     "sentence_id": "s2"}], "relationships": []}
        text = (HERE / "examples/manufacturing.txt").read_text()
        accepted = prototype.process_document(text, "first.txt", self.foundation, self.foundation,
                                              {}, scripted(example_answers()), vectors)
        answer = {"decision": "reuse", "class": "EquipmentInspection", "same_meaning": True, "reason": "Same meaning"}
        reused = prototype.process_document(text, "second.txt", accepted, self.foundation,
                                            {"first.txt": text}, scripted([candidates, answer]), vectors)
        self.assertEqual(reused, accepted)

    def test_skipped_class_skips_its_relationship(self):
        answers = example_answers()
        answers[1] = {"decision": "skip", "reason": "Unsure"}
        answers[-1]["relationships"].pop(0)
        log = {}
        text = (HERE / "examples/manufacturing.txt").read_text()
        result = prototype.process_document(text, "sample.txt", self.foundation, self.foundation,
                                            {}, scripted(answers), vectors, log)
        self.assertEqual(len(result["classes"]), 11)
        self.assertTrue(any(item.get("reason") == "An endpoint class was skipped" for item in log["decisions"]))

    def test_broader_type_without_equivalence_confirmation_is_skipped(self):
        answers = example_answers()
        answers[1] = {"decision": "reuse", "class": "Agent", "same_meaning": False, "reason": "Broader type"}
        answers[-1]["relationships"].pop(0)
        text = (HERE / "examples/manufacturing.txt").read_text()
        log = {}
        result = prototype.process_document(text, "sample.txt", self.foundation, self.foundation,
                                            {}, scripted(answers), vectors, log)
        self.assertNotIn("QualityInspector", graph.classes_by_name(result))
        self.assertEqual(log["decisions"][0]["decision"], "skip")

    def test_null_and_hierarchy_phrase_are_skipped(self):
        answers = example_answers()
        answers[-1]["relationships"][0]["predicate"] = None
        answers[-1]["relationships"][1]["predicate"] = "subClassOf"
        text = (HERE / "examples/manufacturing.txt").read_text()
        result = prototype.process_document(text, "sample.txt", self.foundation, self.foundation,
                                            {}, scripted(answers), vectors)
        self.assertEqual(len(result["relationships"]), 14)

    def test_rejected_edge_keeps_good_work_but_service_error_stops(self):
        for error_kind in ["edge", "model"]:
            with self.subTest(error_kind=error_kind), tempfile.TemporaryDirectory() as directory:
                first = HERE / "examples/manufacturing.txt"
                second = Path(directory) / "z_bad.txt"
                second.write_text(first.read_text())
                output = Path(directory) / "output"
                text = first.read_text()
                expected = prototype.process_document(text, str(first), self.foundation, self.foundation,
                                                      {}, scripted(example_answers()), vectors)
                bad = example_answers()
                # Reuse known classes so the bad mapping reaches the type validator.
                for index, item in enumerate(bad[0]["classes"], start=1):
                    bad[index] = {"decision": "reuse", "class": item["name"], "same_meaning": True, "reason": "Same"}
                bad[-1]["relationships"][0]["predicate"] = "produces"
                ask = scripted(example_answers() + bad)
                if error_kind == "model":
                    first_answers = deque(example_answers())

                    def ask(messages):
                        if first_answers:
                            return first_answers.popleft()
                        raise openai_client.ModelError("Scripted connection failure")
                with patch("sys.stdout", new=StringIO()), patch("sys.stderr", new=StringIO()):
                    ok = prototype.run([second, first], output, "test_rollback", self.foundation,
                                       {}, ask, vectors)
                self.assertEqual(ok, error_kind == "edge")
                self.assertEqual(graph.read_json(output / "graph.json"), expected)
                documents = graph.read_json(output / "decisions.json")["documents"]
                self.assertEqual(documents[0]["source_file"], str(first))
                if error_kind == "model":
                    self.assertEqual(len(documents), 1)
                    failure = graph.read_json(next((output / "failures").glob("*.json")))
                    self.assertEqual(failure["status"], "failed")
                    self.assertIn("model_calls", failure)
                else:
                    self.assertEqual(len(documents), 2)
                    self.assertEqual(documents[1]["summary"]["reject"], 1)
                    self.assertEqual(documents[1]["status"], "accepted_with_rejections")

    def test_invalid_inputs_fail_before_model_calls(self):
        for text in ["", "x" * 3001]:
            with self.subTest(length=len(text)), self.assertRaises(graph.ValidationError):
                prototype.process_document(text, "bad.txt", self.foundation, self.foundation,
                                            {}, scripted([]), vectors)
        answers = example_answers()
        answers[0]["classes"][0]["sentence_id"] = "not_a_source_sentence"
        answers.pop(1)
        answers[-1]["relationships"].pop(0)
        for index, item in enumerate(answers[-1]["relationships"], 1):
            item["id"] = f"r{index}"
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "bad.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertNotIn("QualityInspector", graph.classes_by_name(result))
        self.assertEqual(len(result["classes"]), 11)
        self.assertTrue(any("Unknown source sentence" in item.get("reason", "") for item in log["decisions"]))

    def test_extraction_prompt_example_has_valid_endpoints_and_evidence(self):
        text = "Archivists conduct record reviews"
        instructions = prompts.extraction(text)[0]["content"]
        start = instructions.index('{"classes":')
        example, end = json.JSONDecoder().raw_decode(instructions[start:])
        log = {"decisions": []}
        good = prototype.filter_candidates(example, prompts.source_sentences(text), log)
        self.assertEqual(len(good["classes"]), 2)
        self.assertEqual(len(good["relationships"]), 1)
        self.assertEqual(log["decisions"], [])
        self.assertTrue(all(item["evidence"] == text for item in good["classes"] + good["relationships"]))

    def test_missing_extracted_endpoint_is_logged_without_discarding_valid_class(self):
        text = "Quality inspectors conduct equipment inspections."
        malformed = {
            "classes": [{"id": "c1", "name": "QualityInspector",
                         "description": "An agent that inspects equipment.", "sentence_id": "s1"}],
            "relationships": [{"source": "c1", "phrase": "conduct", "target": "c2",
                               "sentence_id": "s1"}],
        }
        log = {"decisions": []}
        good = prototype.filter_candidates(malformed, prompts.source_sentences(text), log)
        self.assertEqual(len(good["classes"]), 1)
        self.assertEqual(good["relationships"], [])
        self.assertEqual(log["decisions"][0]["decision"], "reject")
        self.assertIn("c2", log["decisions"][0]["reason"])

    def test_model_quotes_are_ignored_and_raw_response_is_preserved(self):
        answers = example_answers()
        relation = answers[0]["relationships"][0]
        relation["evidence"] = "An invented quote"
        log = {}
        text = (HERE / "examples/manufacturing.txt").read_text()
        result = prototype.process_document(text, "sample.txt", self.foundation, self.foundation,
                                            {}, scripted(answers), vectors, log)
        edge = next(edge for edge in result["relationships"] if edge["predicate"] == "performs" and edge["source"] == "QualityInspector")
        self.assertEqual(edge["evidence"], prompts.source_sentences(text)["s1"])
        raw = log["model_calls"][0]["response"]["relationships"][0]
        self.assertEqual(raw["evidence"], "An invented quote")

    def test_document_can_be_called_directly_without_cli_or_database_setup(self):
        log = {}
        text = (HERE / "examples/manufacturing.txt").read_text()
        result = prototype.process_document(text, ask=scripted(example_answers()), embedder=vectors, log=log)
        self.assertEqual(len(result["classes"]), 12)
        self.assertEqual(log["source_file"], "input.txt")
        self.assertEqual(log["summary"]["new"], 5)

    def test_sentence_ids_handle_arithmetic_clause_without_quote_copying(self):
        text = "Every arithmetic operation accepts numbers as input parameters, depends on numeric inputs being available, and produces numbers as results."
        answers = [
            {"classes": [
                {"id": "c1", "name": "Number", "description": "A numeric value.", "sentence_id": "s1"},
                {"id": "c5", "name": "ArithmeticOperation", "description": "A calculation action.", "sentence_id": "s1"},
            ], "relationships": [
                {"source": "c5", "phrase": "depends on", "target": "c1", "sentence_id": "s1"},
            ]},
            {"decision": "new", "parent": "Value", "reason": "A number is a value"},
            {"decision": "new", "parent": "Action", "reason": "A calculation is an action"},
            {"relationships": [{"id": "r1", "predicate": "dependsOn", "reason": "Numeric input is required"}]},
        ]
        result = prototype.process_document(text, "arithmetic.txt", self.foundation, self.foundation,
                                            {}, scripted(answers), vectors)
        edge = next(edge for edge in result["relationships"] if edge["predicate"] == "dependsOn")
        self.assertEqual(edge["evidence"], text)
        self.assertEqual(edge["source"], "ArithmeticOperation")
        graph.validate(result, self.foundation, {"arithmetic.txt": text})

    def test_unknown_relationship_sentence_id_is_rejected(self):
        answers = example_answers()
        answers[0]["relationships"][0]["sentence_id"] = "s999"
        answers[-1]["relationships"].pop(0)
        for index, item in enumerate(answers[-1]["relationships"], 1):
            item["id"] = f"r{index}"
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(len(result["classes"]), 12)
        self.assertEqual(len(result["relationships"]), 15)
        self.assertEqual(log["summary"]["reject"], 1)
        self.assertIn("s999", next(item["reason"] for item in log["decisions"] if item["decision"] == "reject"))

    def test_sentence_numbering_preserves_decimals_and_source_words(self):
        text = "A number can be 4.5. Another can be 2.0.\nAn operation accepts inputs and produces results."
        sentences = prompts.source_sentences(text)
        self.assertEqual(list(sentences.values()), [
            "A number can be 4.5.", "Another can be 2.0.",
            "An operation accepts inputs and produces results.",
        ])
        self.assertTrue(all(sentence in text for sentence in sentences.values()))

    def test_duplicate_mapping_ids_drop_only_ambiguous_and_missing_answers(self):
        answers = example_answers()
        answers[-1]["relationships"][-1]["id"] = "r1"
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "bad.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(log["summary"]["reject"], 2)
        self.assertEqual(log["summary"]["add"], 2)
        self.assertEqual(len(result["classes"]), 12)
        self.assertEqual(len(result["relationships"]), 14)

    def test_new_run_uses_only_current_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for domain in ["manufacturing", "hr"]:
                file = HERE / "examples" / f"{domain}.txt"
                with patch("sys.stdout", new=StringIO()):
                    self.assertTrue(prototype.run([file], output, "test_fresh", self.foundation,
                                                  {}, scripted(example_answers(domain)), vectors))
            result = graph.read_json(output / "graph.json")
            self.assertIn("Recruiter", graph.classes_by_name(result))
            self.assertNotIn("QualityInspector", graph.classes_by_name(result))
            self.assertEqual(len(graph.read_json(output / "decisions.json")["documents"]), 1)
            self.assertEqual({path.name for path in output.iterdir()},
                             {"graph.json", "decisions.json", "params.json", "schema.cypher"})

    def test_echoed_placement_is_rejected_and_other_classes_survive(self):
        answers = example_answers()
        echo = {"candidate": answers[0]["classes"][0], "existing_classes": [], "exact_name_match": None}
        answers[1] = echo
        answers[-1]["relationships"].pop(0)
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(len(result["classes"]), 11)
        self.assertNotIn("QualityInspector", graph.classes_by_name(result))
        self.assertIn("EquipmentInspection", graph.classes_by_name(result))
        self.assertEqual(log["summary"], {"new": 4, "reuse": 0, "add": 3, "skip": 1, "reject": 1})
        self.assertEqual(log["status"], "accepted_with_rejections")
        self.assertEqual(log["model_calls"][1]["response"], echo)
        rejected = next(item for item in log["decisions"] if item["decision"] == "reject")
        self.assertEqual(rejected["stage"], "placement")
        self.assertIn("Unknown placement decision", rejected["reason"])

    def test_bad_parent_rejects_only_that_class_and_dependent_relationship(self):
        answers = example_answers()
        answers[1]["parent"] = "Thing"
        answers[-1]["relationships"].pop(0)
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(log["summary"]["reject"], 1)
        self.assertEqual(log["summary"]["skip"], 1)
        self.assertEqual(len(result["classes"]), 11)
        self.assertNotIn("QualityInspector", graph.classes_by_name(result))
        for original in self.foundation["classes"]:
            self.assertEqual(graph.classes_by_name(result)[original["name"]], original)

    def test_malformed_placement_json_is_logged_and_later_decisions_continue(self):
        answers = example_answers()
        answers[-1]["relationships"].pop(0)
        pending = deque(answers)

        def ask(messages):
            answer = pending.popleft()
            if answer == answers[1]:
                raise openai_client.ModelOutputError("Malformed placement JSON", {"message": {"content": "bad JSON"}})
            return answer

        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, ask, vectors, log)
        self.assertEqual(len(result["classes"]), 11)
        self.assertEqual(log["summary"]["reject"], 1)
        self.assertEqual(log["model_calls"][1]["response"]["message"]["content"], "bad JSON")

    def test_unusable_mapping_batch_keeps_all_accepted_classes(self):
        answers = example_answers()
        answers[-1] = {"unrelated": "This is not a relationship mapping"}
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(len(result["classes"]), 12)
        self.assertEqual(len(result["relationships"]), 12)
        self.assertEqual(log["summary"]["reject"], 4)
        self.assertEqual(log["summary"]["new"], 5)

    def test_unknown_extraction_endpoint_does_not_discard_other_relationships(self):
        answers = example_answers()
        answers[0]["relationships"][0]["target"] = "not_extracted"
        answers[-1]["relationships"].pop(0)
        for index, item in enumerate(answers[-1]["relationships"], 1):
            item["id"] = f"r{index}"
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(log["summary"]["reject"], 1)
        self.assertEqual(log["summary"]["add"], 3)
        self.assertEqual(len(result["classes"]), 12)

    def test_duplicate_candidate_ids_are_all_rejected_as_ambiguous(self):
        answers = example_answers()
        answers[0]["classes"][1]["id"] = "c1"
        del answers[1:3]
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(len(result["classes"]), 10)
        self.assertNotIn("QualityInspector", graph.classes_by_name(result))
        self.assertNotIn("EquipmentInspection", graph.classes_by_name(result))
        self.assertEqual(log["summary"]["reject"], 6)

    def test_missing_explanations_do_not_reject_structurally_valid_decisions(self):
        answers = example_answers()
        for answer in answers[1:-1]:
            answer.pop("reason")
        for answer in answers[-1]["relationships"]:
            answer.pop("reason")
        log = {}
        result = prototype.process_document((HERE / "examples/manufacturing.txt").read_text(), "sample.txt",
                                            self.foundation, self.foundation, {}, scripted(answers), vectors, log)
        self.assertEqual(len(result["classes"]), 12)
        self.assertEqual(log["summary"]["reject"], 0)
        self.assertTrue(all(item["reason"] == "No reason supplied by model" for item in log["decisions"]))

    def test_unreadable_extraction_skips_document_and_processes_next_file(self):
        with tempfile.TemporaryDirectory() as directory, patch("sys.stdout", new=StringIO()), patch("sys.stderr", new=StringIO()):
            bad = Path(directory) / "a_bad.txt"
            bad.write_text("Some source text.")
            output = Path(directory) / "output"
            answers = [{"echo": "No extraction lists"}] + example_answers()
            ok = prototype.run([HERE / "examples/manufacturing.txt", bad], output, "test_continue",
                               self.foundation, {}, scripted(answers), vectors)
            self.assertFalse(ok)  # Run reports an incomplete document, but still saves later good work.
            self.assertEqual(len(graph.read_json(output / "graph.json")["classes"]), 12)
            self.assertEqual(len(graph.read_json(output / "decisions.json")["documents"]), 1)
            failure = graph.read_json(next((output / "failures").glob("*.json")))
            self.assertIn("no class or relationship list", failure["error"])


if __name__ == "__main__":
    unittest.main()
