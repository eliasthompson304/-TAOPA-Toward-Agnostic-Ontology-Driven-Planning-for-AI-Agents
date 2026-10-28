# First prototype

Python turns short workplace text into a proposed type graph using the OpenAI API. It checks the protected foundation and the five predicates, exports JSON and parameterized Cypher, and writes accepted results to Neo4j. Use Python 3.10 or newer and install the dependencies below. `--export-only` skips Neo4j but still uses the OpenAI API.

The purpose is to measure ontology quality and human correction effort. Passing graph checks does not establish correct meanings or better agent reliability. [PLAN.md](PLAN.md) explains the design; [REPORT.md](REPORT.md) links each component to its paper and pseudocode.

The foundation now has `Thing` as its root, with disjoint `Entity` and `Action` branches. `Value`, `InformationObject`, `PhysicalObject`, and `Agent` descend from `Entity`. The foundation also includes `Agent performs Action` as a protected type-level association. New domain classes attach under `Entity` or `Action`, and parameter/output types use the `Entity` branch. This is the user's requested swap of the original Thing/Entity positions. Existing database data and saved outputs are updated only when you explicitly reset or rerun the prototype.

## Run it

From this folder, activate the local environment and install the dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The client reads `OPENAI_API_KEY` from your environment first, then from the repo root's `.env.local` (one folder above this folder). The existing local file is used automatically, even when you launch Python from another directory. Keep it untracked; never put the key in Python code, CLI arguments, prompts, or output files.

Defaults are [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna) for generation and [`text-embedding-3-small`](https://developers.openai.com/api/docs/guides/embeddings) for embeddings. Source text and class descriptions are sent to OpenAI when you run the pipeline. Generation uses the [Responses API in JSON mode](https://developers.openai.com/api/docs/guides/structured-outputs#json-mode) with `store=False` and a 4,096-token output limit. The default generation model uses `reasoning={"effort": "none"}` for short calls; explicit model overrides use their own default reasoning setting. The key is checked locally before the CLI resets Neo4j or replaces output files. A local check does not verify API access or credit availability.

Start your Neo4j database, then set the connection details. Defaults are shown here:

```sh
export NEO4J_URI=neo4j://127.0.0.1:7687
export NEO4J_USERNAME=neo4j
export NEO4J_DATABASE=neo4j
python3 prototype.py --domain arithmetic examples/arithmetic.txt
```

The command prompts for the Neo4j password without displaying it. For a noninteractive run, set `NEO4J_PASSWORD` in your local environment. Passwords are never added to graph files or audit logs. You can also choose `--neo4j-uri`, `--neo4j-username`, and `--neo4j-database` on the command line.

**Every fresh run deletes all nodes and relationships in the selected Neo4j database, across all namespaces.** It reloads the seven protected foundation classes in the same transaction, then adds each validated document without clearing between documents. Each command below therefore replaces the preceding domain in that database. Existing indexes and constraints stay in place.

```sh
python3 prototype.py --domain manufacturing examples/manufacturing.txt examples/manufacturing_02.txt
python3 prototype.py --domain hr examples/hr.txt
```

To write local files without accessing Neo4j:

```sh
python3 prototype.py --export-only --domain arithmetic examples/arithmetic.txt
```

Choose models explicitly with `--generation-model MODEL_ID` and `--embedding-model MODEL_ID`. The program never substitutes a different model automatically. `--timeout` and `--output` are also configurable; see `python3 prototype.py --help`. The API destination is fixed to `https://api.openai.com/v1`; `OPENAI_BASE_URL` does not redirect requests.

Use `.txt` files up to 3,000 characters. A folder argument processes its immediate `.txt` files in filename order. Keep domains separate: the default outputs are `output/manufacturing/` and `output/hr/`, with namespaces `first_prototype_manufacturing` and `first_prototype_hr`. Do not pass the whole mixed-domain `examples` folder as one domain.

## Reset to the foundation only

From this folder, run:

```sh
python3 reset_foundation.py --domain arithmetic
```

This deletes **all nodes and relationships in the selected Neo4j database**, across all namespaces, then loads only the seven protected classes, six `subClassOf` relationships, and `Agent performs Action` (seven relationships total). It stops without processing documents or calling OpenAI; no OpenAI key is required. Use the same domain as your prototype run. The domain sets the foundation's namespace; it does not limit what is deleted. Connection flags and `NEO4J_*` environment variables work as in `prototype.py`, and a missing password is requested privately. Local output and failure files are left as they are. Database indexes and constraints remain.

## Output and failures

- `graph.json`: accepted classes and relationships, with evidence.
- `schema.cypher` and `params.json`: fixed Cypher statements and their values. The Neo4j writer uses the same templates. The database reset is performed by Python when a fresh connected run begins.
- `decisions.json`: settings, original source text, raw model calls, accepted proposals, rejected proposals with their stage and reason, skipped decisions, processing time, and counts for each document.
- `failures/`: unreadable document extractions and errors that stop a run, with raw replies and decisions made so far. Invalid proposals are never exported as accepted graph data.

Each run starts from the foundation and processes all supplied files in filename order. Accepted classes from earlier documents are available to later documents during that run. Repeating a command processes its inputs again. Local output starts with the foundation and is replaced as documents pass validation. Use a different `--output` folder to preserve a previous experiment's files; the connected run still clears the selected database.

An invalid LLM extraction record, placement, or relationship is rejected individually. Valid decisions from the same document are kept. Relationships depending on a skipped placement are skipped too. Duplicate candidate IDs are ambiguous, so all classes with that ID are rejected. A missing or duplicate relationship mapping rejects only the affected relationship. A missing explanation is logged without rejecting an otherwise valid decision. There are no automatic retries or guessed repairs, including in the OpenAI SDK. API errors are logged as status codes or a generic connection message; SDK error bodies are omitted because authentication errors can include key fragments. For HTTP 429, recognized error codes distinguish temporary rate limits from exhausted credits, quota, and spend limits. Unknown codes produce a generic message rather than exposing server text. Check API billing or limits for quota errors; wait and pace calls for temporary rate limits.

Documents with rejected decisions have status `accepted_with_rejections`. Their summary counts `new` classes, `reuse` decisions, accepted relationship proposals (`add`), `skip`, and `reject`. The terminal prints these counts. If every proposal is rejected, the graph stays unchanged and the counts show zero accepted decisions. Exit code 0 means processing finished; it does not establish ontology quality.

If the extraction reply cannot be read at all, its document is logged in `failures/` and later files are still processed. The command eventually returns exit code 1 to indicate an unprocessed document. Unavailable models, connection failures, unusable embeddings, database/disk errors, or an unexpected failure of the final graph checks stop the run. Earlier saved results remain available. A failed database write rolls back that document's database transaction. Exports are written after the database transaction as separate files; a disk error or interrupted write can leave local files out of sync. Rerun the full command to regenerate them. Do not edit generated files; keep human corrections in a separate `corrected_graph.json`. Failure logs from earlier runs remain in `failures/`, with timestamps identifying each attempt.

The only predicates are `subClassOf`, `produces`, `performs`, `dependsOn`, and `acceptsParam`. The graph describes types; it records no individual people or events. Reuse depends on the model's same-meaning judgment, which Python cannot prove. Read the audit log even when all checks pass. Logs contain the source text and model prompts, so keep them with the corresponding workplace data.

For evidence, Python numbers the source sentences (`s1`, `s2`, ...). The model returns a `sentence_id` for each candidate; Python copies that sentence into the saved `evidence` field. Unknown IDs are rejected. This avoids asking the model to reproduce quotes verbatim. The raw reply stays in the audit log. A valid sentence ID proves traceability, not that the sentence supports the proposed meaning; human review must still check that.

## Review the result

Before inspecting model output, review the expected shapes in [examples/REVIEW.md](examples/REVIEW.md) and establish your reference. Copy `review_template.json` into the output folder as `review.json`. Record review and correction time, missed concepts, incorrect parents, and relationship corrections. Preserve the generated graph and save corrections separately. The program leaves these human measurements blank; it does not invent evaluation results.

## Read and call the Python directly

Start with `process_document` in [prototype.py](prototype.py). It follows four steps: extract candidates, place classes, map relationships, and check the final graph. [prompts.py](prompts.py) contains the model instructions; [graph.py](graph.py) contains the graph rules. The OpenAI and Neo4j clients handle their respective connections.

From this folder, ordinary Python can run a document without command-line setup:

```python
from pathlib import Path
from prototype import process_document

text = Path("examples/arithmetic.txt").read_text()
log = {}
graph = process_document(text, source_file="examples/arithmetic.txt", log=log)
print(log["summary"])
```

This call uses the default OpenAI models and the same local API key and returns a graph in memory. It makes no Neo4j writes and does not export files; those steps remain in `run` and the CLI. Imports make no model calls or database changes. The same functions can later be called from a notebook; the source remains ordinary `.py` files.

Each extraction record is checked once. Classes and relationships are checked before being appended, and the complete graph is checked at document boundaries. The log keeps raw model calls, decisions, counts, and timing; duplicate intermediate candidate lists, full graph snapshots, and redundant attempt IDs have been removed.

## Check the code without API calls

```sh
python3 -m unittest -v
```

Tests use scripted JSON responses, small number lists in place of models, and a fake Neo4j driver. They exercise both domains, partial acceptance, rejected placements and relationships, evidence, graph constraints, exports, database reset timing, and service failures. API adapter tests use the real OpenAI SDK with a mock HTTP transport and fake keys. They check request format, refusal and incomplete output handling, embedding order, credential loading, and sanitized errors. No tests contact OpenAI or a real database. Live examples were deliberately not run during implementation, as requested.
