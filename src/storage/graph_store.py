from neo4j import GraphDatabase
from src.config import settings
from src.models.company import Company


class GraphStore:
    _instance = None

    def __init__(self):
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    @classmethod
    def get_instance(cls) -> "GraphStore":
        """Singleton — évite de multiplier les connexions driver."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def close(self):
        self.driver.close()
        GraphStore._instance = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def create_constraints(self):
        with self.driver.session() as session:
            session.run("""
                CREATE CONSTRAINT company_name_unique IF NOT EXISTS
                FOR (c:Company)
                REQUIRE c.name IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT tier_level_unique IF NOT EXISTS
                FOR (t:Tier)
                REQUIRE t.level IS UNIQUE
            """)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert_company(self, company: Company):
        query = """
        MERGE (c:Company {name: $name})
        SET c.website       = $website,
            c.country       = $country,
            c.tier          = $tier,
            c.description   = $description,
            c.email         = $email,
            c.phone         = $phone,
            c.address       = $address,
            c.linkedin      = $linkedin,
            c.contact_name  = $contact_name,
            c.services      = $services,
            c.certifications = $certifications,
            c.source        = $source,
            c.confidence    = $confidence
        """
        with self.driver.session() as session:
            session.run(query, {
                "name":           company.name,
                "website":        company.website,
                "country":        company.country,
                "tier":           company.tier,
                "description":    company.description,
                "email":          company.email,
                "phone":          company.phone,
                "address":        company.address,
                "linkedin":       company.linkedin,
                "contact_name":   company.contact_name,
                "services":       company.services or [],
                "certifications": company.certifications or [],
                "source":         company.source,
                "confidence":     company.confidence,
            })

    def upsert_discovered_company(self, name: str, source_company: str):
        """Crée un noeud Company minimal pour un partenaire découvert par scraping."""
        with self.driver.session() as session:
            session.run(
                """
                MERGE (c:Company {name: $name})
                ON CREATE SET c.source = $source,
                              c.discovered_via = $via
                """,
                {"name": name, "source": "discovered", "via": source_company},
            )

    def link_company_to_tier(self, company_name: str, tier: int):
        """Crée le noeud Tier et relie la Company avec BELONGS_TO."""
        if not tier or tier not in (1, 2):
            return
        label = {1: "Fabricants coffrets", 2: "Sous-traitants câblage"}[tier]
        with self.driver.session() as session:
            session.run(
                """
                MERGE (t:Tier {level: $tier})
                SET t.label = $label
                WITH t
                MATCH (c:Company {name: $name})
                MERGE (c)-[:BELONGS_TO]->(t)
                """,
                {"tier": tier, "label": label, "name": company_name},
            )

    def create_mention_relation(self, source_name: str, mentioned_name: str):
        """Relation MENTIONS — source cite mentioned sur son site."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (a:Company {name: $source})
                MATCH (b:Company {name: $mentioned})
                WHERE a <> b
                MERGE (a)-[:MENTIONS]->(b)
                """,
                {"source": source_name, "mentioned": mentioned_name},
            )

    def create_supplies_relation(self, supplier_name: str, client_name: str):
        """Relation SUPPLIES — fournisseur confirmé (mention bidirectionnelle)."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (s:Company {name: $supplier})
                MATCH (c:Company {name: $client})
                WHERE s <> c
                MERGE (s)-[:SUPPLIES]->(c)
                """,
                {"supplier": supplier_name, "client": client_name},
            )

    def create_potential_supplier(self, supplier_name: str, client_name: str, reason: str):
        """Relation POTENTIAL_SUPPLIER avec raison (région, domaine, etc.)."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (s:Company {name: $supplier})
                MATCH (c:Company {name: $client})
                WHERE s <> c
                MERGE (s)-[r:POTENTIAL_SUPPLIER]->(c)
                SET r.reason = $reason
                """,
                {"supplier": supplier_name, "client": client_name, "reason": reason},
            )

    def detect_and_upgrade_supplies(self):
        """
        Si A -[MENTIONS]-> B ET B -[MENTIONS]-> A → créer A -[SUPPLIES]-> B.
        Mention bidirectionnelle = relation fournisseur confirmée.
        """
        with self.driver.session() as session:
            session.run("""
                MATCH (a:Company)-[:MENTIONS]->(b:Company)-[:MENTIONS]->(a)
                WHERE a <> b
                MERGE (a)-[:SUPPLIES]->(b)
            """)

    def update_embedding(self, company_name: str, embedding: list[float]):
        with self.driver.session() as session:
            session.run(
                "MATCH (c:Company {name: $name}) SET c.embedding = $embedding",
                {"name": company_name, "embedding": embedding},
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_all_companies(self) -> list[dict]:
        query = """
        MATCH (c:Company)
        RETURN c.name    AS name,
               c.website AS website,
               c.country AS country,
               c.tier    AS tier,
               c.address AS address
        """
        with self.driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

    def get_company_names(self) -> list[str]:
        """Retourne la liste de tous les noms d'entreprises connus."""
        with self.driver.session() as session:
            result = session.run("MATCH (c:Company) RETURN c.name AS name")
            return [record["name"] for record in result]

    def get_known_domains(self) -> set[str]:
        """Retourne les domaines (extraits de website) des entreprises déjà dans Neo4j."""
        from urllib.parse import urlparse
        with self.driver.session() as session:
            result = session.run(
                "MATCH (c:Company) WHERE c.website IS NOT NULL RETURN c.website AS website"
            )
            domains = set()
            for record in result:
                url = record["website"] or ""
                try:
                    host = urlparse(url if url.startswith("http") else f"https://{url}").netloc.lower()
                    if host:
                        domains.add(host.replace("www.", ""))
                except Exception:
                    pass
            return domains

    def get_companies_by_tier(self, tier: int) -> list[dict]:
        query = """
        MATCH (c:Company {tier: $tier})
        RETURN c.name       AS name,
               c.website    AS website,
               c.country    AS country,
               c.email      AS email,
               c.address    AS address,
               c.confidence AS confidence
        ORDER BY c.confidence DESC
        """
        with self.driver.session() as session:
            result = session.run(query, {"tier": tier})
            return [record.data() for record in result]
