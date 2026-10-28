"""Send the validated type graph to Neo4j using the official Python driver."""

# User-requested persistence, not a research algorithm. ANCHOR IV-D describes
# optional Cypher serialization, but our driver transactions, destructive reset,
# and class-level storage format are local choices (REPORT.md, component 9).
# https://arxiv.org/html/2606.01208v1#S4.SS4

from graph import cypher_queries


class DatabaseError(ValueError):
    """Neo4j is unavailable or could not save the graph."""


def connect(uri, username, password):
    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import DriverError, Neo4jError
    except ImportError as error:
        raise DatabaseError("Install the Neo4j driver: python3 -m pip install -r requirements.txt") from error
    driver = GraphDatabase.driver(uri, auth=(username, password),
                                  connection_timeout=5, max_transaction_retry_time=0)
    try:
        driver.verify_connectivity()
    except (DriverError, Neo4jError, OSError) as error:
        driver.close()
        raise DatabaseError("Cannot connect to Neo4j; check the server, URI, username, and password") from error
    return driver


def write_graph(driver, database, graph, ontology, clear=False):
    from neo4j.exceptions import DriverError, Neo4jError

    queries, params = cypher_queries(graph, ontology)

    def save(transaction):
        if clear:
            transaction.run("MATCH (n) DETACH DELETE n").consume()
        for query in queries[1:]:
            transaction.run(query, params).consume()

    try:
        with driver.session(database=database) as session:
            # Schema changes must be separate from the data transaction.
            session.run(queries[0]).consume()
            session.execute_write(save)
    except (DriverError, Neo4jError, OSError) as error:
        raise DatabaseError(f"Neo4j write failed for database {database}; its data transaction was rolled back") from error
