from typing import TypedDict
from operator import add


class AgentState(TypedDict):
    status:              str
    prospects_found:     int
    prospects_scraped:   int
    competitors_found:   int
    marketing_insights:  dict
    report_path:         str
    messages:            list
    errors:              list[str]
    max_per_query:       int
    limit_scraping:      int