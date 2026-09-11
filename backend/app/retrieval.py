from __future__ import annotations

import math
import re

from collections import Counter
from dataclasses import dataclass


TOKEN = re.compile(
    r"[a-zA-Z0-9+#.-]{2,}"
)


@dataclass(frozen=True)
class Chunk:
    source: str
    text: str


# ============================================================
# INTERVIEW QUERY EXPANSION
# ============================================================

INTENT_EXPANSIONS = {
    "production_issue": [
        "production",
        "issue",
        "incident",
        "failure",
        "failed",
        "error",
        "problem",
        "challenge",
        "debug",
        "troubleshoot",
        "root cause",
        "fix",
        "resolved",
        "resolution",
        "rerun",
        "reconciliation",
        "mismatch",
        "count mismatch",
        "duplicate",
        "duplicates",
        "data quality",
        "pipeline failure",
        "job failure",
        "support",
    ],

    "current_project": [
        "current project",
        "project",
        "client",
        "role",
        "responsibilities",
        "architecture",
        "pipeline",
        "data",
        "development",
        "production",
        "implementation",
        "integration",
    ],

    "responsibilities": [
        "responsibilities",
        "role",
        "developed",
        "designed",
        "implemented",
        "created",
        "maintained",
        "supported",
        "validated",
        "monitored",
        "reconciliation",
        "deployment",
    ],

    "cdc": [
        "cdc",
        "change data capture",
        "incremental",
        "incremental load",
        "change column",
        "merge",
        "upsert",
        "insert",
        "update",
        "datebound",
        "date bound",
    ],

    "duplicates": [
        "duplicate",
        "duplicates",
        "deduplication",
        "row_number",
        "qualify",
        "merge key",
        "business key",
        "delete",
        "data quality",
    ],

    "reconciliation": [
        "reconciliation",
        "source target",
        "source-to-target",
        "count mismatch",
        "row count",
        "validation",
        "data quality",
        "sanity check",
    ],

    "pipeline": [
        "pipeline",
        "etl",
        "elt",
        "ingestion",
        "extract",
        "transform",
        "load",
        "orchestration",
        "scheduler",
        "job",
        "workflow",
    ],

    "bigquery": [
        "bigquery",
        "partition",
        "partitioning",
        "cluster",
        "clustering",
        "query",
        "bytes scanned",
        "cost",
        "performance",
        "optimization",
    ],

    "gcp": [
        "gcp",
        "google cloud",
        "bigquery",
        "dataflow",
        "dataproc",
        "pubsub",
        "pub/sub",
        "composer",
        "gcs",
        "cloud storage",
    ],

    "snowflake": [
        "snowflake",
        "warehouse",
        "sql",
        "merge",
        "cdc",
        "etl",
        "data warehouse",
    ],

    "security": [
        "iam",
        "service account",
        "least privilege",
        "role",
        "permission",
        "access",
        "security",
        "credential",
    ],
}


def chunk_text(
    source: str,
    text: str,
    size: int = 900,
    overlap: int = 150,
) -> list[Chunk]:

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if not text:
        return []

    out: list[Chunk] = []
    start = 0

    while start < len(text):
        end = min(
            len(text),
            start + size,
        )

        if end < len(text):
            cut = text.rfind(
                ". ",
                start + size // 2,
                end,
            )

            if cut > start:
                end = cut + 1

        out.append(
            Chunk(
                source=source,
                text=text[start:end],
            )
        )

        if end == len(text):
            break

        start = max(
            start + 1,
            end - overlap,
        )

    return out


def _terms(
    text: str,
) -> Counter[str]:

    return Counter(
        t.lower()
        for t in TOKEN.findall(text)
    )


def _normalize(
    text: str,
) -> str:

    return re.sub(
        r"\s+",
        " ",
        text.lower(),
    ).strip()


def _expand_query(
    query: str,
) -> str:

    q = _normalize(query)

    expansions: list[str] = []

    # --------------------------------------------------------
    # Production / challenge questions
    # --------------------------------------------------------

    if (
        "challenge" in q
        or "challenging" in q
        or "production issue" in q
        or "production problem" in q
        or "issue you faced" in q
        or "problem you faced" in q
        or "how you resolved" in q
        or "how you solved" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "production_issue"
            ]
        )

    # --------------------------------------------------------
    # Current project / role
    # --------------------------------------------------------

    if (
        "current project" in q
        or "your project" in q
        or "project you are working" in q
        or "tell me about your project" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "current_project"
            ]
        )

    if (
        "responsibil" in q
        or "your role" in q
        or "what do you do" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "responsibilities"
            ]
        )

    # --------------------------------------------------------
    # Technical topics
    # --------------------------------------------------------

    if (
        "cdc" in q
        or "change data capture" in q
        or "incremental" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS["cdc"]
        )

    if (
        "duplicate" in q
        or "dedup" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "duplicates"
            ]
        )

    if (
        "reconcil" in q
        or "count mismatch" in q
        or "source to target" in q
        or "source-to-target" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "reconciliation"
            ]
        )

    if (
        "pipeline" in q
        or "etl" in q
        or "elt" in q
        or "ingestion" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "pipeline"
            ]
        )

    if "bigquery" in q:
        expansions.extend(
            INTENT_EXPANSIONS[
                "bigquery"
            ]
        )

    if (
        "gcp" in q
        or "google cloud" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS["gcp"]
        )

    if "snowflake" in q:
        expansions.extend(
            INTENT_EXPANSIONS[
                "snowflake"
            ]
        )

    if (
        "iam" in q
        or "service account" in q
        or "least privilege" in q
    ):
        expansions.extend(
            INTENT_EXPANSIONS[
                "security"
            ]
        )

    if not expansions:
        return query

    unique = list(
        dict.fromkeys(
            expansions
        )
    )

    return (
        query
        + " "
        + " ".join(unique)
    )


def _source_bonus(
    source: str,
    query: str,
) -> float:

    source_l = source.lower()
    query_l = query.lower()

    bonus = 0.0

    experience_question = any(
        phrase in query_l
        for phrase in [
            "your experience",
            "your project",
            "current project",
            "your role",
            "responsibil",
            "challenge",
            "challenging",
            "production issue",
            "example",
            "where have you used",
            "tell me about",
        ]
    )

    if experience_question:
        if "project" in source_l:
            bonus += 0.12

        if (
            "responsibil" in source_l
            or "role" in source_l
        ):
            bonus += 0.12

        if (
            "resume" in source_l
            or "professional" in source_l
        ):
            bonus += 0.06

    return bonus


def search(
    chunks: list[Chunk],
    query: str,
    limit: int = 7,
) -> list[Chunk]:

    if not chunks:
        return []

    expanded_query = _expand_query(
        query
    )

    q = _terms(
        expanded_query
    )

    original_q = _terms(
        query
    )

    docs = [
        _terms(c.text)
        for c in chunks
    ]

    df = Counter(
        term
        for doc in docs
        for term in doc
    )

    n = len(docs)


    def lexical_score(
        doc: Counter[str],
    ) -> float:

        total = (
            sum(doc.values())
            or 1
        )

        score = 0.0

        for term, query_count in q.items():
            if not doc[term]:
                continue

            idf = math.log(
                (n + 1)
                /
                (df[term] + 0.5)
            )

            score += (
                (
                    1
                    + math.log(
                        doc[term]
                    )
                )
                * idf
                * (
                    1
                    + math.log(
                        query_count
                    )
                )
                / total
            )

        return score


    def original_term_bonus(
        doc: Counter[str],
    ) -> float:

        matched = sum(
            1
            for term in original_q
            if doc[term]
        )

        if not original_q:
            return 0.0

        return (
            matched
            /
            len(original_q)
        ) * 0.20


    scored = []

    for chunk, doc in zip(
        chunks,
        docs,
    ):
        score = lexical_score(
            doc
        )

        score += original_term_bonus(
            doc
        )

        score += _source_bonus(
            chunk.source,
            query,
        )

        if score > 0:
            scored.append(
                (
                    score,
                    chunk,
                )
            )


    scored.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )


    results: list[Chunk] = []
    seen: set[str] = set()

    for _, chunk in scored:

        signature = re.sub(
            r"\s+",
            " ",
            chunk.text.lower(),
        )[:180]

        if signature in seen:
            continue

        seen.add(signature)

        results.append(
            chunk
        )

        if len(results) >= limit:
            break


    return results


# Live answers use actual content overlap, without injecting unrelated documents
# or broad topic expansions when no evidence matches.
LIVE_STOP=set("a an and are as at be been but by can could did do does for from had has have how i if in into is it its me my of on or our should so than that the their them then there these they this those to was we were what when where which who why will with would you your first next explain describe tell about example question answer use used using data project experience approach please".split())
def search_live(chunks: list[Chunk], query: str, limit: int = 4) -> list[Chunk]:
    def terms(value):
        return set(t.lower() for t in re.findall(r"[^\W_]+(?:[+#.-][^\W_]+)*", value, re.UNICODE) if len(t)>1 and t.lower() not in LIVE_STOP)
    q=terms(query)
    if not q:return []
    docs=[terms(c.text) for c in chunks]
    counts=Counter(t for doc in docs for t in doc)
    scored=[]
    for chunk,doc in zip(chunks,docs):
        overlap=q & doc
        if not overlap:continue
        score=sum(math.log(1+len(chunks)/(1+counts[t])) for t in overlap)/math.sqrt(max(1,len(doc)))
        scored.append((score,chunk))
    scored.sort(key=lambda item:item[0],reverse=True)
    if not scored:return []
    return [chunk for score,chunk in scored[:limit] if score>=scored[0][0]*0.35]
