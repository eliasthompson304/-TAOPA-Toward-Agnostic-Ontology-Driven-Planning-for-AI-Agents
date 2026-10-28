"""Clear the selected Neo4j database and reload only the protected foundation."""

# Local database maintenance, not a research algorithm. This deliberately uses
# only the graph and Neo4j helpers, so no OpenAI key or model call is required.
import argparse
import getpass
import os
from pathlib import Path
import sys

from graph import identifier, load_foundation, nonempty_text, require
import neo4j_client


HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help="Namespace used by the prototype, e.g. arithmetic")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687"))
    parser.add_argument("--neo4j-username", default=os.environ.get("NEO4J_USERNAME", "neo4j"))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()
    driver = None
    try:
        require(identifier(args.domain), "Domain must be an identifier")
        foundation = load_foundation(HERE / "foundation.json")
        password = os.environ.get("NEO4J_PASSWORD")
        if not password:
            require(sys.stdin.isatty(), "Set NEO4J_PASSWORD or run in a terminal to enter the password")
            password = getpass.getpass("Neo4j password: ")
        require(nonempty_text(password), "Neo4j password is required")
        driver = neo4j_client.connect(args.neo4j_uri, args.neo4j_username, password)
        print(f"Clearing all data in Neo4j database {args.neo4j_database} at {args.neo4j_uri}.", flush=True)
        neo4j_client.write_graph(driver, args.neo4j_database, foundation,
                                "first_prototype_" + args.domain, clear=True)
        print("Foundation restored: 7 classes and 6 subClassOf relationships.")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Reset failed: {error}", file=sys.stderr)
        return 1
    finally:
        if driver is not None:
            driver.close()


if __name__ == "__main__":
    sys.exit(main())
