# First prototype: component report

This report describes the program in [PLAN.md](PLAN.md). The pseudocode explains its steps; runnable Python is linked below. Each component names its source and the simplification used. Offline tests verify the implementation; live model quality and human effort remain unmeasured.

The papers provide selected ideas. The seven-class foundation, exact five predicates, simple Python rules, and class-level graph meanings are our prototype design. We are not claiming to reproduce the papers' complete systems or results.

The current foundation follows the user's requested position swap: `Thing` is the root; `Entity` and `Action` are its disjoint children; `Value`, `InformationObject`, `PhysicalObject`, and `Agent` are children of `Entity`. Placement rules and predicate endpoint checks use this revised foundation. The foundation also includes the user-requested `Agent performs Action` association. It is a type-level association, with no source-document evidence required. These foundation choices are local design decisions, not findings from the papers. Earlier saved run artifacts retain the foundation used at the time of those runs.

The north star is to test whether automatically extended foundational ontologies are accurate enough to support neuro-symbolic reliability benefits with less human effort. This report separates three kinds of evidence: Python checks measure structural compliance, human review measures ontology quality and correction effort, and a future agent experiment must measure downstream reliability. Success in one does not establish success in the next.

## Research grounding assessment

Source/code review on 2026-10-18: this is a reasonably grounded synthesis of selected research ideas, with limited fidelity to the complete methods and no measured evidence yet for its quality or reliability benefits. The paper guide below links the primary sources. Python comments now identify the relevant paper and section beside each component, including where an attribution is only an inspiration.

| Component | Assessment against the papers |
| --- | --- |
| Text extraction | A clear conceptual match to OntoEKG III-B. This implementation replaces its extraction machinery and does not reproduce its entailment or RDF serialization stages. |
| Class ranking and placement | Description/cosine comparison follows the DOLCE/ITSMO idea. ANCHOR is a looser influence: three matches plus ancestors replace its recursive discovery. Turning schema typing into a reuse/new-subclass decision is a substantial adaptation. |
| Context and integration | OntoExtend motivates read-only context and deduplicated integration. Documents, JSON, and a protected single-parent graph replace its requirement-driven ontology fragments. |
| Relationship mapping | A clear conceptual match to EDC's target-alignment decision, with rejection allowed. The separate definition, retrieval, and refinement stages are omitted. |
| Validation | The general check-before-acceptance pattern is supported; our Python invariants are a narrower, custom implementation. They do not provide SHACL validation or general OWL reasoning. |
| OpenAI and Neo4j clients | Provider and storage plumbing. Using OpenAI changes experimental settings; it supplies no independent evidence that the borrowed methods work here. |

The main unresolved issue is semantic correctness. `same_meaning` is a model assertion; a permitted parent need not be the correct parent; and a literal source sentence need not support the proposed meaning. A correct class outside the retrieved context cannot be selected. Placement also depends on candidate order because parents must already exist, and accepted definitions and parents cannot later be revised. The seven classes, five predicates, evidence mechanism, and partial-acceptance policy are local assumptions to evaluate.

The checked-in `output/arithmetic/decisions.json` currently contains zero completed document records, and there are no `output/*/review.json` files. Those artifacts do not establish ontology accuracy, reduced human effort, or downstream agent reliability. The existing offline tests exercise program contracts with mocks. The next evidence should come from the reference and human-review exercise in section 10, followed by comparisons against simpler baselines (for example, full-context placement without embedding retrieval) using the same models and inputs. A separate downstream task experiment is needed for reliability claims.

This annotation change adds comments only to the eight Python files in this prototype. Syntax parsing, AST comparison, and executable-token comparison confirmed unchanged executable code; no live model or database run was needed.

## Implementation map

| Components below | Implementation |
| --- | --- |
| 1. Load and protect foundation | [foundation.json](foundation.json), [graph.py](graph.py), [prototype.py](prototype.py) |
| 2. OpenAI calls | [openai_client.py](openai_client.py) |
| 3. Extract | [prompts.py](prompts.py), `filter_candidates` in [prototype.py](prototype.py) |
| 4. Rank; 5. Reuse or place; 6. Map phrases | `placement_context`, `place_candidate`, and `map_relationships` in [prototype.py](prototype.py) |
| 7. Validate; 9. Export and upload | [graph.py](graph.py), [neo4j_client.py](neo4j_client.py) |
| 8. Integrate and log | `process_document`, `run`, and `save_outputs` in [prototype.py](prototype.py) |
| 10. Human review | [review_template.json](review_template.json), [examples/REVIEW.md](examples/REVIEW.md) |
| Offline verification | [test_graph.py](test_graph.py), [test_neo4j.py](test_neo4j.py), [test_openai.py](test_openai.py) |

The program saves raw prompts, replies, proposals, source text, settings, and processing time. Each run starts from the foundation; later documents in that run can reuse earlier accepted additions. Accepted results overwrite the generated output files. Human review fields stay blank until measured. No live model examples were run during implementation, as requested.

The readability refactor keeps the same model prompts and graph behavior. Extraction checks run once per record. `add_class` and `add_relationship` check additions before modifying the document's working graph; complete validation runs at document boundaries. Duplicate candidate lists, full graph snapshots in audit logs, and redundant attempt IDs were removed. `process_document(text, log=...)` is callable directly from Python, while file output and Neo4j writes remain explicit. No notebook conversion was made.

At the user's request, handling was changed from aborting a document on an invalid proposal to rejecting decisions individually. Each valid proposal must still satisfy the same graph rules. Rejected and skipped decisions remain in the audit log alongside accepted decisions and counts; this policy is our implementation choice, not an additional paper algorithm.

## Paper guide

| Paper | Relevant section | Idea borrowed | Simplification |
| --- | --- | --- | --- |
| [OntoEKG: LLM-Driven Ontology Construction for Enterprise Knowledge Graphs](https://arxiv.org/html/2602.01276v1) | III-B, Pipeline | Extract classes and properties from enterprise text into structured records | The model returns JSON; plain Python checks it; keep evidence; replace the entailment and serialization stages |
| [ANCHOR: Schema-Agnostic Knowledge Graph Construction via Hybrid Ontology Discovery for Cyber Threat Intelligence](https://arxiv.org/html/2606.01208v1) | IV-C and IV-D | Combine semantic search with ontology structure; validate before committing | Rank a small list, include ancestors, and use Python checks; no recursive discovery agent or SHACL |
| [OntoExtend: A Framework for Requirement-driven and Scalable Ontology Extension with LLMs](https://arxiv.org/html/2607.17963v1) | 3.2, 3.3, and 4 | Generate with existing ontology context, deduplicate, integrate, and evaluate using questions | Use workplace text, read-only JSON context, one-parent additions, and a small manual review |
| [Automating Ontology Mapping in IT Service Management: A DOLCE and ITSMO Integration](https://datascience.codata.org/articles/10.5334/dsj-2025-023) | Similarity computation approaches | Use class labels and descriptions for embedding similarity and LLM compatibility judgments | Use our foundation, OpenAI, and one parent choice; no DOLCE import, GNN, repeated scoring, or statistical clustering |
| [EDC: Extract, Define, Canonicalize](https://arxiv.org/html/2404.03868v1) | 3.1, Target Alignment | Verify a phrase's meaning against a fixed schema; exclude unsuitable mappings | Give the model all five predicate definitions; allow `null`; Python checks names and endpoint types |

ANCHOR types extracted entities against an existing schema. Our “reuse an equivalent class or add a subclass” decision adapts that idea to schema extension. OntoExtend starts from competency questions; our pipeline starts from documents and uses questions only for evaluation. Evidence quotes and the fixed predicate contract are added requirements here.

## 1. Load text and protect the foundation

**Source:** User's architecture and local foundation rules; file loading is ordinary program plumbing.

**Job:** Read one short text file and make a private graph copy. The foundation always starts with the same seven class definitions, six parent edges, and the protected `Agent performs Action` association.

```python
text = read_text(file)
if text is empty or len(text) > 3000:
    stop("Use a nonempty text file up to 3,000 characters")

check_starting_graph(accepted_graph, foundation)
working_graph = copy(accepted_graph)
decisions = []
```

Keep each domain's accepted graph separate. Failed work must not change it.

## 2. Call OpenAI for generation and embeddings

**Source:** The user's updated provider requirement; the official [Responses JSON mode documentation](https://developers.openai.com/api/docs/guides/structured-outputs#json-mode) and [embedding guide](https://developers.openai.com/api/docs/guides/embeddings). This is connection code, not a research algorithm.

**Job:** Replace local model calls with OpenAI calls while keeping the existing prompts, graph contract, partial acceptance, and Neo4j behavior. Defaults are `gpt-6-luna` for generation and `text-embedding-3-small` for embeddings; both are configurable. The default generation model runs without extra reasoning; explicit model overrides use their own default reasoning setting.

```python
key = environment_key_or_repo_local_env_file()
# The key goes only to the SDK, never into the prompt or audit log.
client = OpenAI(api_key=key, base_url="https://api.openai.com/v1",
                timeout=120, max_retries=0)

def ask_json(messages):
    reply = client.responses.create(
        model=GENERATION_MODEL,
        input=messages,
        text={"format": {"type": "json_object"}},
        max_output_tokens=4096,
        store=False,
        reasoning={"effort": "none"},  # for the default generation model
    )
    reject_if_incomplete_or_refused(reply)
    return parse_json_object(reply.output_text)

def embed(texts):
    reply = client.embeddings.create(
        model=EMBEDDING_MODEL, input=texts, encoding_format="float")
    items = sort_by_input_index(reply.data)
    check_indexes_match_inputs(items, texts)
    return check_vectors([item.embedding for item in items])
```

Read `OPENAI_API_KEY` from the environment first, otherwise from the repo root's ignored `.env.local`, using its path relative to the Python source. Do not modify that file or load its values into the global environment. Imports make no requests. The CLI checks key presence before resetting Neo4j or replacing output; it does not make a paid request to verify the key. The API destination is fixed even if `OPENAI_BASE_URL` is set.

Malformed, refused, or incomplete generation is a rejected model decision; the existing per-decision handling still applies. API status errors stop processing with their status code, without storing SDK error bodies that may contain credential fragments. For HTTP 429, a small list of recognized codes distinguishes rate limits from credits, quota, and spend limits; unknown labels and raw messages are omitted. Connection failures use a generic message. Check that embedding counts and indexes match inputs and that vectors have matching lengths, finite numbers, and nonzero lengths. No automatic retries are used.

This provider change follows the user's instruction. It changes the model being evaluated, not the borrowed paper algorithms; quality comparisons with earlier outputs must record that difference. No live API examples were run during the refactor.

## 3. Extract candidate classes and phrases

**Source:** OntoEKG, Section III-B, extraction stage.

**Job:** Turn workplace text into small records with names, definitions, and source sentence IDs. We add local IDs and literal evidence requirements. We do not copy its full code or reproduce its entailment stage.

```python
sentences = number_source_sentences(text)
candidates = ask_json(extraction_prompt(sentences))
check_required_fields(candidates)
check_unique_candidate_ids(candidates)

for item in all_candidate_records(candidates):
    if item["sentence_id"] not in sentences:
        log_rejection(item, "Unknown source sentence")
        continue
    item["evidence"] = sentences[item["sentence_id"]]
    check_quote_occurs_in_source(item["evidence"], text)
```

The prompt asks for types such as `QualityInspector`, not individual people. Relations initially keep phrases such as “conduct”; they cannot enter the final graph until mapped. After repeated model-written quote failures, extraction was changed to select numbered source sentences. Python attaches the exact text; the unmodified model reply remains in the log. This is an implementation refinement for traceability, not a semantic correctness check. A model can still select a sentence that does not support its proposal.

## 4. Rank existing classes with embeddings

**Source:** Simplified ANCHOR discovery and DOLCE/ITSMO description-based comparison.

**Job:** Compare a candidate's name and description with existing classes. An ordinary loop is enough for this small graph. Embeddings rank options; they never establish equivalence by themselves.

```python
candidate_vector = embed([candidate_name_and_description])[0]
scores = []
for existing_class in existing_extension_classes(working_graph):
    existing_vector = get_or_make_cached_vector(existing_class)
    score = cosine(candidate_vector, existing_vector)
    scores.append((existing_class["name"], score))

matches = three_highest_scoring_extension_classes(scores)
context = foundation_definitions + matches + ancestors_of(matches)
```

Cosine compares the direction of two number lists: add the matching-number products, then divide by the product of their lengths. Use the same embedding model and text format for both sides. The foundation is always included, even when a foundation class ranks poorly.

## 5. Reuse a class or choose one parent

**Source:** ANCHOR inspires matching against existing structure; DOLCE/ITSMO inspires definition-based compatibility; OntoExtend inspires read-only context. The new-class decision is our addition.

**Job:** Preserve old definitions and add only useful, attached classes.

```python
answer = ask_json(placement_prompt(candidate, context, exact_name_match))

if answer["decision"] == "reuse":
    check_existing_name(answer["class"])
    record_mapping(candidate["id"], answer["class"])
elif answer["decision"] == "new":
    check_unused_name(candidate["name"])
    check_existing_parent(answer["parent"])
    check_parent_descends_from_entity_or_action(answer["parent"])
    add_class_to_working_copy(candidate, answer["parent"])
    record_mapping(candidate["id"], candidate["name"])
else:
    log_skip(candidate, answer["reason"])
```

Check output fields and permitted decision values before these branches. Exact names receive the same meaning check. `QualityInspector` is narrower than `Agent`: it should become a subclass, rather than disappear through reuse. A conflicting name or uncertain meaning is skipped for review. Parents must already exist in the working copy; a later candidate cannot be a parent yet.

## 6. Map relationship phrases to the fixed predicates

**Source:** EDC, Section 3.1, target alignment. Its central idea here is semantic verification, including the option to exclude a relationship.

**Job:** Keep exactly this list:

```python
PREDICATES = ["subClassOf", "produces", "performs", "dependsOn", "acceptsParam"]
```

```python
ready_relations = resolve_ids_and_log_missing_endpoints(candidates)
answers = ask_json(mapping_prompt(ready_relations, predicate_definitions))
check_one_answer_for_each_relation(answers, ready_relations)

for relation, answer in matching_answers(ready_relations, answers):
    predicate = answer["predicate"]
    if predicate is None:
        log_skip(relation, "No suitable predicate")
    elif predicate not in PREDICATES:
        log_rejection(relation, "Unknown predicate")
    elif predicate == "subClassOf":
        log_skip(relation, "Hierarchy comes from parent selection")
    else:
        try_edge_and_keep_it_only_if_valid(relation, predicate)
```

“Conduct” may map to `performs` for an Agent-to-Action pair. “Works near” should be left out. Give the model all five definitions rather than retrieving predicates with another index. Parent selection supplies `subClassOf`; Python still validates every edge.

## 7. Validate the proposal

**Source:** Validation before acceptance is inspired by ANCHOR and OntoExtend. The particular Python checks, single-parent limit, protected foundation, and fixed endpoint table are our design.

**Job:** Catch structural errors without another model call.

```python
check_record_shapes(working_graph)
check_foundation_unchanged(working_graph, foundation)
check_previous_definitions_and_parents_unchanged(working_graph, accepted_graph)

for edge in working_graph["relationships"]:
    check_predicate_and_endpoints(edge)

for name in all_class_names(working_graph):
    parents = find_parents(name)
    check_parent_count(name, parents)
    ancestors = walk_parents_and_detect_cycles(name)
    reject_if_both_entity_and_action(ancestors)
    check_connection_to_foundation(name, ancestors)

for edge in domain_edges(working_graph):
    check_source_and_target_types(edge)

check_new_evidence_against_source(new_records, text)
```

`walk_parents_and_detect_cycles` follows parent links and remembers visited names; seeing a name twice on that chain means a cycle. The one-parent limit makes this easy to follow. Type checks use those ancestors and the table in the plan.

These checks cannot prove that a proposed definition is true or that the graph covers the document.

## 8. Integrate and keep a decision log

**Source:** OntoExtend, Section 3.3, inspires deduplication and integration. Per-decision rejection and local audit files are our choices, updated at the user's request to retain valid work when the LLM makes mistakes.

**Job:** Keep valid decisions, reject invalid decisions, and make both visible. Check the final combined graph before publishing it.

```python
for decision in proposed_decisions:
    try:
        check_decision_before_adding(working_graph, decision)
    except InvalidModelDecision as error:
        log_rejection(decision, error)
    else:
        append_valid_decision(working_graph, decision)
        log_acceptance(decision)

validate_complete_graph(working_graph)
save_json("graph.json", working_graph)
save_json("decisions.json", decisions_and_counts)
```

The log records source file, candidate ID, evidence, new/reuse/add/skip/reject decision, chosen class or parent, reason, mapped predicate, and validation outcome. Rejected records include the failed stage and proposal; raw replies remain unchanged. Duplicate local class IDs are ambiguous and all such records are rejected. Missing or duplicate relationship mappings affect only those requested relationships. Missing explanations get a log note. Dependencies on rejected placements are skipped. Each document has summary counts and uses `accepted_with_rejections` when appropriate. Record model tags and settings once per run. Later documents can reuse accepted additions. A reused definition is never overwritten by new evidence.

An unreadable extraction skips only that document and is saved in `failures/`; later files still run, with a final nonzero exit code indicating incomplete document coverage. Service, embedding, database, disk, or unexpected final-graph errors still stop the run. There are no automatic retries or guessed repairs. A low rejection count alone does not establish quality: count missing concepts and review the accepted meanings too.

## 9. Export JSON parameters and Cypher, then write Neo4j

**Source:** User's Python/Cypher requirement and later request to clear Neo4j on every fresh run; storage and database reset are ordinary application code. ANCHOR also describes optional Cypher output, but we use our own small class graph format.

**Job:** Keep local graph files and send validated graphs to the selected Neo4j database.

```python
params = {"ontology": domain_namespace, "classes": accepted_graph["classes"]}
for predicate in PREDICATES:
    params[predicate] = edges_with_predicate(accepted_graph, predicate)

save_json("params.json", params)
write_text("schema.cypher", FIXED_CYPHER_TEMPLATES)

# At the start of a connected run, before any model calls:
write_graph(driver, database, foundation, namespace, clear=True)

# After each document passes validation:
write_graph(driver, database, accepted_graph, namespace)
```

The templates use actual relationship types with exactly the five allowed spellings. Values stay in parameters. The plan includes example statements. JSON files contain the graph and audit data; no extra evidence nodes or relationships are needed. The official Neo4j driver executes the same templates. A fresh connected run deletes every node and relationship in the selected database and inserts the protected foundation in one data transaction; subsequent document transactions add validated results without clearing again. The program gets connection settings from flags or environment variables and prompts privately for a missing password. `--export-only` skips database access.

## 10. Run two domains and review the result

**Source:** OntoExtend's question-driven evaluation and human assessment, adapted to two tiny document sets. DOLCE/ITSMO also uses human-adjudicated mappings; our review is deliberately small.

**Job:** Check whether the output is useful, not merely structurally valid.

```python
for domain in ["manufacturing", "hr"]:
    graph = copy(foundation)
    for file in sorted_files(domain):
        graph = process_document(file, graph)

    compare_with_human_reference(graph, reference_for(domain))
    record_missed_classes_and_wrong_parents()
    record_wrong_predicates_and_manual_corrections()
    record_human_review_and_correction_minutes()
    check_two_domain_questions(graph)
```

Create the human reference before reading generated output. Include all five predicates in the manufacturing exercise, a repeated concept to test reuse, and a phrase with no suitable predicate to test rejection. Report actual counts and errors without importing performance numbers from the papers.

Keep raw and corrected graphs. Record time spent creating the reference separately from time spent correcting model output. Count omissions and skipped concepts as well as incorrect additions; producing very little should not look like high quality. Use these small examples to decide what to improve and test next, without claiming proven labor savings or downstream reliability gains.

## What this prototype will demonstrate

One protected foundation can be extended from short workplace documents using OpenAI models, while Python enforces a small graph contract and Cypher preserves the result. Whether the model chooses good concepts and parents remains an experimental question answered by the local runs and human review.
