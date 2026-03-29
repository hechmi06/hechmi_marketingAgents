from src.models.company import Company
from src.storage.graph_store import GraphStore

company = Company(
    name="Depagne",
    website="https://www.depagne.fr",
    country="France",
    tier=1,
    description="Fabricant de coffrets de comptage électrique",
    source="manual",
    confidence=0.95
)

gs = GraphStore()
gs.create_constraints()
gs.upsert_company(company)

companies = gs.get_all_companies()
for c in companies:
    print(c)

gs.close()