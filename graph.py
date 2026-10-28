"""Small graph rules. No model calls and no database connection."""

import json
from pathlib import Path
import re


# Local ontology contract from PLAN.md and foundation.json, not an imported
# DOLCE ontology or a predicate set established by any of the cited papers.
PREDICATES = ["subClassOf", "produces", "performs", "dependsOn", "acceptsParam"]
PARENTS = {
    "Thing": None, "Entity": "Thing", "Value": "Entity",
    "InformationObject": "Entity", "PhysicalObject": "Entity",
    "Agent": "Entity", "Action": "Thing",
}
PREDICATE_MEANINGS = {
    "subClassOf": "Every member of a new class belongs to its existing parent class.",
    "produces": "Action -> Entity: possible output type.",
    "performs": "Agent -> Action: kind of action associated with an agent type.",
    "dependsOn": "Action -> Entity or Action: required resource or prerequisite type.",
    "acceptsParam": "Action -> Entity: allowed input type; multiple targets are alternatives.",
}


class ValidationError(ValueError):
    """A proposal broke a rule."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def edge_key(edge):
    return (edge["source"], edge["predicate"], edge["target"])


def classes_by_name(graph):
    return {item["name"]: item for item in graph["classes"]}


# Ordinary graph traversal supporting placement and validation, not ANCHOR's
# LLM-guided recursive ontology discovery algorithm.
def ancestors(graph, name):
    """Include the class itself; reject a repeated name on a parent path."""
    parents = {}
    for edge in graph["relationships"]:
        if edge["predicate"] == "subClassOf":
            parents.setdefault(edge["source"], []).append(edge["target"])
    found = set()
    pending = [(name, [])]
    while pending:
        current, path = pending.pop()
        require(current not in path, f"Subclass cycle at {current}")
        found.add(current)
        for parent in parents.get(current, []):
            pending.append((parent, path + [current]))
    return found


# Local provenance check: literal occurrence is necessary for traceability,
# but it does not check whether the text entails the class or relationship.
def check_evidence(record, sources, label="record"):
    source = record.get("source_file")
    quote = record.get("evidence")
    require(nonempty_text(source) and source in sources, f"Unknown source file for {label}")
    require(nonempty_text(quote) and quote in sources[source], f"Missing literal source quote for {label}: {quote!r}")


# Local endpoint table for our five predicates; not an OWL reasoner or SHACL.
def check_relationship_types(predicate, source, target):
    """Source and target contain their ancestor names, including themselves."""
    if predicate == "performs":
        valid = "Agent" in source and "Action" in target
    elif predicate in ["produces", "acceptsParam"]:
        valid = "Action" in source and "Entity" in target
    elif predicate == "dependsOn":
        valid = "Action" in source and bool({"Entity", "Action"} & target)
    else:
        valid = False
    require(valid, f"Wrong source or target type for {predicate}")


def load_foundation(path):
    foundation = read_json(path)
    require(isinstance(foundation, dict), "Foundation must be an object")
    require(isinstance(foundation.get("classes"), list), "Foundation needs classes")
    require(isinstance(foundation.get("relationships"), list), "Foundation needs relationships")
    names = [item.get("name") for item in foundation["classes"] if isinstance(item, dict)]
    require(len(names) == 7 and set(names) == set(PARENTS), "Foundation must have the seven protected classes")
    expected = set()
    for name, parent in PARENTS.items():
        if parent is not None:
            expected.add((name, "subClassOf", parent))
    for edge in foundation["relationships"]:
        require(isinstance(edge, dict), "Foundation edges must be objects")
        require(all(nonempty_text(edge.get(key)) for key in ["source", "predicate", "target"]),
                "Foundation edge needs source, predicate, and target")
    actual = {edge_key(edge) for edge in foundation["relationships"]}
    require(actual == expected and len(foundation["relationships"]) == 6, "Foundation parents changed")
    validate(foundation, foundation, {})
    return foundation


# ANCHOR IV-D and OntoExtend 3.2 motivate checking proposals before acceptance:
# https://arxiv.org/html/2606.01208v1#S4.SS4
# https://arxiv.org/html/2607.17963v1#S3.SS2
# These Python invariants are ours: protected foundation, one parent, disjoint
# branches, fixed endpoints, literal evidence, and append-only accepted data.
# No SHACL repair loop, Turtle validation, or general OWL consistency checking.
# Passing cannot establish correct meanings, coverage, or agent reliability.
def validate(graph, foundation, sources, previous=None):
    require(isinstance(graph, dict), "Graph must be an object")
    require(isinstance(graph.get("classes"), list), "Graph needs a class list")
    require(isinstance(graph.get("relationships"), list), "Graph needs a relationship list")
    names = set()
    for item in graph["classes"]:
        require(isinstance(item, dict), "Class must be an object")
        name = item.get("name")
        require(identifier(name), "Invalid class name")
        require(name not in names, f"Duplicate class: {name}")
        names.add(name)
        require(nonempty_text(item.get("description")), f"Missing description: {name}")
        require(type(item.get("foundation")) is bool, "Foundation flag must be a boolean")
        require(item["foundation"] == (name in PARENTS), f"Wrong foundation flag: {name}")
        if name not in PARENTS:
            check_evidence(item, sources)

    current = classes_by_name(graph)
    for original in foundation["classes"]:
        require(current.get(original["name"]) == original, "Protected foundation class changed")

    foundation_edges = {edge_key(edge): edge for edge in foundation["relationships"]}
    unique_edges = {}
    parents = {name: set() for name in names}
    for edge in graph["relationships"]:
        require(isinstance(edge, dict), "Relationship must be an object")
        require(all(nonempty_text(edge.get(key)) for key in ["source", "predicate", "target"]),
                "Relationship needs source, predicate, and target")
        require(edge["predicate"] in PREDICATES, f"Unknown predicate: {edge['predicate']}")
        require(edge["source"] in names and edge["target"] in names, "Unknown relationship endpoint")
        key = edge_key(edge)
        if key in foundation_edges:
            require(edge == foundation_edges[key], "Protected foundation edge changed")
        else:
            check_evidence(edge, sources)
        if edge["predicate"] == "subClassOf":
            parents[edge["source"]].add(edge["target"])
            if edge["source"] in PARENTS:
                require(key in foundation_edges, "Protected foundation parent changed")
        unique_edges.setdefault(key, edge)
    require(set(foundation_edges).issubset(unique_edges), "Missing foundation edge")

    family = {}
    for name in names:
        family[name] = ancestors(graph, name)
        require(not {"Entity", "Action"}.issubset(family[name]), "Entity and Action are disjoint")
        wanted_count = 0 if name == "Thing" else 1
        require(len(parents[name]) == wanted_count, f"{name} must have {wanted_count} parent(s)")
        if name not in PARENTS:
            require(bool({"Entity", "Action"} & family[name]), f"{name} must descend from Entity or Action")

    for edge in graph["relationships"]:
        if edge["predicate"] != "subClassOf":
            check_relationship_types(edge["predicate"], family[edge["source"]], family[edge["target"]])

    if previous is not None:
        for old in previous["classes"]:
            require(current.get(old["name"]) == old, "Existing class definition changed")
        old_edges = {edge_key(edge): edge for edge in previous["relationships"]}
        for key, old in old_edges.items():
            require(unique_edges.get(key) == old, "Existing relationship changed or removed")

    # Keep the first copy of an edge; extra evidence remains in the decision log.
    graph["relationships"] = list(unique_edges.values())


# Local incremental enforcement of the same graph contract as validate().
def add_class(graph, candidate, parent, source_file):
    """Check first, then attach one new class. Existing classes are never edited."""
    names = classes_by_name(graph)
    require(candidate["name"] not in names, "Class name already exists")
    require(parent in names, f"Unknown parent: {parent}")
    require(bool({"Entity", "Action"} & ancestors(graph, parent)), "Parent must descend from Entity or Action")
    graph["classes"].append({
        "name": candidate["name"], "description": candidate["description"],
        "foundation": False, "source_file": source_file, "evidence": candidate["evidence"],
    })
    graph["relationships"].append({
        "source": candidate["name"], "predicate": "subClassOf", "target": parent,
        "source_file": source_file, "evidence": candidate["evidence"],
    })


# OntoExtend 3.3 inspires deduplication during integration:
# https://arxiv.org/html/2607.17963v1#S3.SS3
# Here only identical (source, predicate, target) keys are deduplicated; this
# does not discover differently named but semantically equivalent concepts.
def add_relationship(graph, edge):
    """Check first, then append a domain relationship if it is new."""
    names = classes_by_name(graph)
    require(edge["source"] in names and edge["target"] in names, "Unknown relationship endpoint")
    require(edge["predicate"] in PREDICATES, "Unknown mapped predicate")
    check_relationship_types(edge["predicate"], ancestors(graph, edge["source"]), ancestors(graph, edge["target"]))
    for existing in graph["relationships"]:
        if edge_key(existing) == edge_key(edge):
            return
    graph["relationships"].append(edge)


# User-requested Neo4j representation and parameterized storage plumbing.
# ANCHOR also offers Cypher output, but these templates are our implementation.
CONSTRAINT = """CREATE CONSTRAINT first_prototype_class IF NOT EXISTS
FOR (c:OntologyClass) REQUIRE (c.ontology, c.name) IS UNIQUE"""
CLASS_QUERY = """UNWIND $classes AS item
MERGE (c:OntologyClass {ontology: $ontology, name: item.name})
ON CREATE SET c.description = item.description, c.foundation = item.foundation,
              c.source_file = item.source_file, c.evidence = item.evidence"""


def cypher_queries(graph, ontology):
    """Only our fixed five labels go into query text. Model output stays in parameters."""
    require(identifier(ontology), "Ontology namespace must be an identifier")
    queries = [CONSTRAINT, CLASS_QUERY]
    params = {"ontology": ontology, "classes": graph["classes"]}
    for label in PREDICATES:
        params[label] = [edge for edge in graph["relationships"] if edge["predicate"] == label]
        queries.append(f"""UNWIND ${label} AS edge
MATCH (a:OntologyClass {{ontology: $ontology, name: edge.source}})
MATCH (b:OntologyClass {{ontology: $ontology, name: edge.target}})
MERGE (a)-[r:{label}]->(b)
ON CREATE SET r.source_file = edge.source_file, r.evidence = edge.evidence""")
    return queries, params


def cypher_export(graph, ontology):
    queries, params = cypher_queries(graph, ontology)
    return ";\n\n".join(queries) + ";\n", params
