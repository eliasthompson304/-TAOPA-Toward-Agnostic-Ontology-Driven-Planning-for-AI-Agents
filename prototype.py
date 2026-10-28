"""Build a type graph and write Neo4j. Fresh connected runs clear the selected database."""

# Research provenance (adaptations, not reproductions; see REPORT.md):
# OntoEKG, III-B: enterprise-text extraction.
# https://arxiv.org/html/2602.01276v1#S3.SS2
# ANCHOR, IV-C: semantic search with ontology structure.
# https://arxiv.org/html/2606.01208v1#S4.SS3
# OntoExtend, 3.2-3.3: read-only context, reuse, and integration.
# https://arxiv.org/html/2607.17963v1#S3.SS2
# DOLCE/ITSMO, "Similarity computation approaches": description comparison.
# https://datascience.codata.org/articles/10.5334/dsj-2025-023
# EDC, 3.1 (Target Alignment): verify a relation mapping or exclude it.
# https://arxiv.org/html/2404.03868v1#S3.SS1

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import sys
import time

from graph import (PREDICATES, ValidationError, add_class, add_relationship, ancestors,
                   classes_by_name, cypher_export, identifier, load_foundation,
                   nonempty_text, require, validate, write_json)
import openai_client
import neo4j_client
import prompts


HERE = Path(__file__).resolve().parent


class DocumentError(ValueError):
    """No usable extraction was returned for this document."""


# Local audit policy: retain good decisions while recording individual failures.
# This rejection policy is not a paper algorithm.
def reject(log, stage, kind, proposal, reason):
    log["decisions"].append({"stage": stage, "kind": kind, "decision": "reject",
                             "proposal": proposal, "reason": str(reason)})


# OntoEKG III-B motivates the extracted class/property records. Sentence IDs,
# literal evidence attachment, and per-record rejection are local additions;
# selecting an existing sentence does not establish semantic support.
def filter_candidates(raw, sentences, log):
    """Check each record once and attach its original source sentence."""
    if not isinstance(raw, dict):
        raise DocumentError("Extraction must be an object")
    good = {"classes": [], "relationships": []}
    counts = {}
    valid_ids = set()
    raw_classes = raw.get("classes")
    if isinstance(raw_classes, list):
        for item in raw_classes:
            if isinstance(item, dict) and nonempty_text(item.get("id")):
                counts[item["id"]] = counts.get(item["id"], 0) + 1
    for kind in ["classes", "relationships"]:
        items = raw.get(kind)
        if not isinstance(items, list):
            reject(log, "extraction", kind, items, f"Expected a {kind} list")
            continue
        for index, item in enumerate(items, start=1):
            try:
                require(isinstance(item, dict), f"Candidate {kind} #{index} must be an object")
                sentence_id = item.get("sentence_id")
                require(nonempty_text(sentence_id) and sentence_id in sentences,
                        f"Unknown source sentence for candidate {kind} #{index}: {sentence_id!r}")
                if kind == "classes":
                    require(nonempty_text(item.get("id")), "Candidate needs a text ID")
                    require(counts[item["id"]] == 1, "Duplicate candidate ID is ambiguous")
                    require(identifier(item.get("name")), "Invalid candidate class name")
                    require(nonempty_text(item.get("description")), "Candidate needs a description")
                    valid_ids.add(item["id"])
                else:
                    for endpoint in ["source", "target"]:
                        require(nonempty_text(item.get(endpoint)), "Relationship needs text endpoints")
                        require(item[endpoint] in valid_ids, f"Unknown class ID: {item[endpoint]}")
                    require(nonempty_text(item.get("phrase")), "Relationship needs a phrase")
                good[kind].append({**item, "evidence": sentences[sentence_id]})
            except ValidationError as error:
                reject(log, "extraction", "class" if kind == "classes" else "relationship", item, error)
    if not isinstance(raw.get("classes"), list) and not isinstance(raw.get("relationships"), list):
        raise DocumentError("Extraction has no class or relationship list")
    return good


# Ordinary application instrumentation, not a research contribution: preserve
# prompts, raw replies, and timing so later human review can inspect decisions.
def call_model(ask, stage, messages, log):
    call = {"stage": stage, "messages": messages}
    log["model_calls"].append(call)
    started = time.monotonic()
    try:
        answer = ask(messages)
    except openai_client.ModelOutputError as error:
        call.update(response=error.response, error=str(error))
        raise
    finally:
        call["seconds"] = round(time.monotonic() - started, 3)
    call["response"] = answer
    require(isinstance(answer, dict), "Model response must be an object")
    return answer


# DOLCE/ITSMO compares class labels and descriptions; this is our text format.
def class_text(item):
    return item["name"] + ": " + item["description"]


# Simplified ANCHOR IV-C: semantic retrieval plus hierarchy context. We take
# three extension classes and their ancestors, always adding the foundation.
# No confidence threshold, recursive discovery agent, or scoped search is used.
# DOLCE/ITSMO motivates description-based cosine ranking; its statistical
# filtering and repeated compatibility scoring are not implemented here.
# The cutoff, cache, and exact-name inclusion are prototype choices, not tuned
# research results. Similarity ranks options; it does not prove equivalence.
def placement_context(graph, candidate, embedder, cache):
    extensions = [item for item in graph["classes"] if not item["foundation"]]
    texts = [class_text(candidate)] + [class_text(item) for item in extensions]
    missing = sorted(set(texts) - set(cache))
    if missing:
        vectors = openai_client.check_vectors(embedder(missing), len(missing))
        for text, vector in zip(missing, vectors):
            cache[text] = vector
    candidate_vector = cache[class_text(candidate)]
    scores = []
    for item in extensions:
        score = openai_client.cosine(candidate_vector, cache[class_text(item)])
        scores.append((score, item["name"]))
    scores.sort(key=lambda pair: (-pair[0], pair[1]))
    names = {item["name"] for item in graph["classes"] if item["foundation"]}
    for score, name in scores[:3]:
        names.update(ancestors(graph, name))
    exact = classes_by_name(graph).get(candidate["name"])
    if exact:
        names.update(ancestors(graph, exact["name"]))
    context = []
    for item in graph["classes"]:
        if item["name"] in names:
            context.append({"name": item["name"], "description": item["description"],
                            "ancestors": sorted(ancestors(graph, item["name"]))})
    exact_context = next((item for item in context if item["name"] == candidate["name"]), None)
    return context, exact_context


# ANCHOR's existing-schema typing is adapted here to class extension.
# OntoExtend 3.2 inspires reuse of read-only context; DOLCE/ITSMO inspires
# meaning-based compatibility. The reuse/new/skip contract and one-parent rule
# are ours. same_meaning is an LLM assertion, not a logical equivalence proof.
def place_candidate(candidate, graph, context, exact, answer, source_file):
    require(answer.get("decision") in ["reuse", "new", "skip"], "Unknown placement decision")
    if not nonempty_text(answer.get("reason")):
        answer = {**answer, "reason": "No reason supplied by model"}
    decision = {**candidate, **answer, "kind": "class", "candidate_id": candidate["id"]}
    if answer["decision"] == "skip":
        return None, decision
    if answer["decision"] == "reuse":
        name = answer.get("class")
        require(nonempty_text(name) and name in classes_by_name(graph), "Cannot reuse an unknown class")
        if answer.get("same_meaning") is not True:
            decision.update(decision="skip", reason="Reuse did not confirm the same meaning")
            return None, decision
        if exact and name != exact["name"]:
            decision.update(decision="skip", reason="Name collision needs human review")
            return None, decision
        require(name in {item["name"] for item in context}, "Reused class was outside provided context")
        return name, decision
    if exact:
        decision.update(decision="skip", reason="Existing name has a different meaning; review needed")
        return None, decision
    parent = answer.get("parent")
    require(nonempty_text(parent), "New class needs one parent name")
    require(parent in {item["name"] for item in context}, "Parent was outside provided context")
    add_class(graph, candidate, parent, source_file)
    return candidate["name"], decision


# EDC 3.1 Target Alignment inspires checking a phrase against schema meanings
# and excluding unsuitable mappings. We supply all five definitions directly;
# EDC's separate relation-definition stage, vector retrieval, and EDC+R are
# absent. Mapping IDs, endpoint checks, and separate parent selection are local.
def map_relationships(candidates, mapping, graph, ask, source_file, log):
    ready = []
    for index, item in enumerate(candidates["relationships"], start=1):
        record = {**item, "id": f"r{index}"}
        if item["source"] not in mapping or item["target"] not in mapping:
            log["decisions"].append({**record, "kind": "relationship", "decision": "skip",
                                     "reason": "An endpoint class was skipped"})
            continue
        record["source"] = mapping[item["source"]]
        record["target"] = mapping[item["target"]]
        record["source_ancestors"] = sorted(ancestors(graph, record["source"]))
        record["target_ancestors"] = sorted(ancestors(graph, record["target"]))
        ready.append(record)
    if not ready:
        return
    try:
        answer = call_model(ask, "relationships", prompts.relationships(ready), log)
        answers = answer.get("relationships")
        require(isinstance(answers, list), "Mapping response needs a relationship list")
    except (ValidationError, openai_client.ModelOutputError) as error:
        for item in ready:
            reject(log, "mapping", "relationship", item, error)
        return
    requested = {item["id"] for item in ready}
    by_id = {}
    for item in answers:
        if not isinstance(item, dict) or not nonempty_text(item.get("id")) or item["id"] not in requested:
            reject(log, "mapping", "relationship", item, "Unknown or missing mapping ID")
        else:
            by_id.setdefault(item["id"], []).append(item)
    for item in ready:
        results = by_id.get(item["id"], [])
        try:
            require(len(results) == 1, "Missing or duplicate relationship mapping ID")
            result = results[0]
            require("predicate" in result, "Mapping needs a predicate")
            predicate = result["predicate"]
            require(predicate is None or predicate in PREDICATES, "Unknown mapped predicate")
            reason = result.get("reason")
            if not nonempty_text(reason):
                reason = "No reason supplied by model"
            decision = {**item, **result, "kind": "relationship", "stage": "mapping", "reason": reason}
            if predicate is None or predicate == "subClassOf":
                log["decisions"].append({**decision, "decision": "skip"})
                continue
            add_relationship(graph, {
                "source": item["source"], "predicate": predicate, "target": item["target"],
                "source_file": source_file, "evidence": item["evidence"],
            })
            log["decisions"].append({**decision, "decision": "add"})
        except ValidationError as error:
            reject(log, "mapping", "relationship", {"candidate": item, "answers": results}, error)


# Combines the adapted extraction, placement, and alignment stages above.
# OntoExtend 3.3 motivates integrating deduplicated additions. The document
# copy, partial acceptance, input limit, and audit counts are local policies.
def process_document(text, source_file="input.txt", accepted=None, foundation=None, sources=None,
                     ask=openai_client.ask_json, embedder=openai_client.embed, log=None, cache=None):
    """Return a new graph. Pass a log dictionary to inspect decisions and raw replies."""
    if foundation is None:
        foundation = load_foundation(HERE / "foundation.json")
    if accepted is None:
        accepted = foundation
    if sources is None:
        sources = {}
    if log is None:
        log = {}
    log.update(source_file=source_file, text=text, status="proposed", decisions=[], model_calls=[])
    working = deepcopy(accepted)
    require(nonempty_text(text) and len(text) <= 3000, "Use a nonempty text file up to 3,000 characters")
    validate(working, foundation, sources)
    document_sources = {**sources, source_file: text}

    # 1. Extract candidates and attach their source sentences.
    try:
        raw = call_model(ask, "extraction", prompts.extraction(text), log)
    except (ValidationError, openai_client.ModelOutputError) as error:
        raise DocumentError(str(error)) from error
    candidates = filter_candidates(raw, prompts.source_sentences(text), log)

    # 2. Reuse or place each class; reject only the bad decisions.
    mapping = {}
    if cache is None:
        cache = {}
    for candidate in candidates["classes"]:
        context, exact = placement_context(working, candidate, embedder, cache)
        answer = None
        try:
            answer = call_model(ask, "placement", prompts.placement(candidate, context, exact), log)
            name, decision = place_candidate(candidate, working, context, exact, answer, source_file)
            log["decisions"].append({**decision, "stage": "placement"})
            if name:
                mapping[candidate["id"]] = name
        except (ValidationError, openai_client.ModelOutputError) as error:
            reject(log, "placement", "class", {"candidate": candidate, "answer": answer}, error)

    # 3. Map phrases and add relationships that pass the type rules.
    map_relationships(candidates, mapping, working, ask, source_file, log)

    # 4. Check the completed graph and count the outcomes.
    validate(working, foundation, document_sources, previous=accepted)
    log["summary"] = {}
    for action in ["new", "reuse", "add", "skip", "reject"]:
        log["summary"][action] = sum(item["decision"] == action for item in log["decisions"])
    log["status"] = "accepted_with_rejections" if log["summary"]["reject"] else "accepted"
    return working


# Local export/audit plumbing, not a paper evaluation or quality metric.
def save_outputs(folder, graph, history):
    """Write the accepted graph, its audit log, and its Cypher export."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    cypher, params = cypher_export(graph, history["ontology"])
    write_json(folder / "graph.json", graph)
    write_json(folder / "decisions.json", history)
    write_json(folder / "params.json", params)
    (folder / "schema.cypher").write_text(cypher, encoding="utf-8")


# OntoExtend 3.3 describes making integrated fragments available to later
# requests (disabled in its evaluation). Here later documents see prior
# accepted classes; this does not reproduce its CQ evaluation protocol.
# Fresh-run reset, file ordering, failure policy, and publication are local.
def run(files, output, ontology, foundation, settings, ask, embedder, publish=None):
    require(identifier(ontology), "Ontology namespace must be an identifier")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    graph = deepcopy(foundation)
    history = {"ontology": ontology, "documents": []}
    sources = {}
    validate(graph, foundation, sources)
    if publish is not None:
        publish(graph, ontology, clear=True)
        print("Neo4j cleared; protected foundation loaded.", flush=True)
    save_outputs(output, graph, history)
    cache = {}
    skipped_documents = False
    paths = set(Path(file).resolve() for file in files)
    for path in sorted(paths, key=lambda item: (item.name, str(item))):
        log = {"source_file": str(path), "settings": settings,
               "started_at": datetime.now(timezone.utc).isoformat()}
        started = time.monotonic()
        try:
            text = path.read_text(encoding="utf-8")
            print(f"Processing: {path.name}", flush=True)
            proposed = process_document(text, str(path), graph, foundation, sources, ask, embedder, log, cache)
            log["processing_seconds"] = round(time.monotonic() - started, 3)
            if publish is not None:
                publish(proposed, ontology)
            history["documents"].append(log)
            save_outputs(output, proposed, history)
            graph = proposed
            sources[str(path)] = text
            summary = log["summary"]
            print(f"Processed: {path.name}; {summary['new']} new classes, {summary['reuse']} reused, "
                  f"{summary['add']} accepted relationship proposals; "
                  f"{summary['reject']} rejected, {summary['skip']} skipped decisions")
        except (ValueError, OSError, KeyError, TypeError) as error:
            log.update(status="failed", error=str(error), processing_seconds=round(time.monotonic() - started, 3))
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            failure = output / "failures" / f"{stamp}.json"
            write_json(failure, log)
            if isinstance(error, DocumentError):
                print(f"Skipped document: {error}. Failure details: {failure}", file=sys.stderr)
                skipped_documents = True
            else:
                print(f"Stopped: {error}. Failure details: {failure}", file=sys.stderr)
                return False
    return not skipped_documents


# User-selected provider/database configuration and CLI plumbing; model choices
# are experimental settings, not evidence that paper results transfer here.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="Short .txt files or folders of .txt files")
    parser.add_argument("--domain", required=True, help="Identifier such as manufacturing or hr")
    parser.add_argument("--output", type=Path, help="Default: output/DOMAIN beside this script")
    parser.add_argument("--generation-model", default=openai_client.GENERATION_MODEL)
    parser.add_argument("--embedding-model", default=openai_client.EMBEDDING_MODEL)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--export-only", action="store_true", help="Write local files without connecting to Neo4j")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687"))
    parser.add_argument("--neo4j-username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()
    driver = None
    try:
        require(identifier(args.domain), "Domain must be an identifier")
        require(args.timeout > 0, "Timeout must be positive")
        files = []
        for path in args.files:
            files.extend(sorted(path.glob("*.txt")) if path.is_dir() else [path])
        require(files and all(path.suffix == ".txt" for path in files), "Supply .txt files")
        for path in files:
            require(path.is_file(), f"Input file not found: {path}")
        foundation = load_foundation(HERE / "foundation.json")
        openai_client.api_key()  # Check credentials before resetting Neo4j or replacing local output.
        settings = {"provider": "openai", "generation_model": args.generation_model,
                    "embedding_model": args.embedding_model, "timeout": args.timeout,
                    "max_output_tokens": openai_client.MAX_OUTPUT_TOKENS, "store": False,
                    "reasoning_effort": "none" if args.generation_model == openai_client.GENERATION_MODEL
                    else "model_default"}
        output = args.output or HERE / "output" / args.domain
        ask = lambda messages: openai_client.ask_json(messages, args.generation_model, args.timeout)
        embedder = lambda texts: openai_client.embed(texts, args.embedding_model, args.timeout)
        publish = None
        if not args.export_only:
            password = os.environ.get("NEO4J_PASSWORD")
            if not password:
                require(sys.stdin.isatty(), "Set NEO4J_PASSWORD or run in a terminal to enter the password")
                password = getpass.getpass("Neo4j password: ")
            require(nonempty_text(password), "Neo4j password is required")
            driver = neo4j_client.connect(args.neo4j_uri, args.neo4j_username, password)
            print(f"Neo4j target: {args.neo4j_uri}, database {args.neo4j_database}", flush=True)

            def publish(graph, ontology, clear=False):
                neo4j_client.write_graph(driver, args.neo4j_database, graph, ontology, clear)

        ok = run(files, output, "first_prototype_" + args.domain, foundation, settings, ask, embedder, publish)
        return 0 if ok else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if driver is not None:
            driver.close()


if __name__ == "__main__":
    sys.exit(main())
