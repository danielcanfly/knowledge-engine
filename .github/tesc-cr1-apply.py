from pathlib import Path
from textwrap import dedent

p = Path('src/knowledge_engine/m26_pa7_arbitrary_query_runtime.py')
s = p.read_text()

old = (
    "        if (\n"
    "            _claim_requires_multi_source(intent_class, claim_role)\n"
    "            and _distinct_source_count(\n"
    "                evidence_by_id[str(ref[\"evidence_id\"])] for ref in ref_records\n"
    "            )\n"
    "            < 2\n"
    "            and not is_model_explanation\n"
    "        ):\n"
    "            raise _verification_failure(\"M26-PA7-ME-021\", \"relational claim lacks two sources\")\n"
)
new = (
    "        if (\n"
    "            _claim_requires_multi_source(intent_class, claim_role)\n"
    "            and _distinct_source_count(\n"
    "                evidence_by_id[str(ref[\"evidence_id\"])] for ref in ref_records\n"
    "            )\n"
    "            < 2\n"
    "            and not is_model_explanation\n"
    "            and not _single_source_synthesis_has_complete_premise_support(\n"
    "                question=question,\n"
    "                surface_text=surface_text,\n"
    "                support_refs=ref_records,\n"
    "            )\n"
    "        ):\n"
    "            raise _verification_failure(\"M26-PA7-ME-021\", \"relational claim lacks complete premise support\")\n"
)
assert s.count(old) == 1, f'ME021 anchor count={s.count(old)}'
s = s.replace(old, new)

marker = 'def _verify_synthesis_premise_binding(\n'
helper = dedent(r'''
def _named_material_entities(text: str) -> set[str]:
    value = str(text)
    entities = {
        item.casefold()
        for item in re.findall(
            r"\bEntity\s+[A-Z0-9]+\b|\b[A-Z][A-Za-z0-9.]*\s+Part\s+\d+\b|\b[A-Z][A-Za-z0-9.]{2,}\b",
            value,
        )
    }
    return {
        item
        for item in entities
        if item not in {"compare", "explain", "what", "when", "which", "does", "why", "how", "the", "for", "if", "answer"}
    }


def _single_source_synthesis_has_complete_premise_support(
    *,
    question: str,
    surface_text: str,
    support_refs: Sequence[Mapping[str, Any]],
) -> bool:
    if not support_refs:
        return False
    support_text = " ".join(str(ref.get("exact_quote", "")) for ref in support_refs).strip()
    surface = str(surface_text).strip()
    if not support_text or not surface:
        return False
    required_named = _named_material_entities(surface) & _named_material_entities(question)
    supported_named = _named_material_entities(support_text)
    if required_named and not required_named.issubset(supported_named):
        return False
    surface_terms = _meaningful_terms(surface) - _relevance_common_terms()
    support_terms = _meaningful_terms(support_text) - _relevance_common_terms()
    if not surface_terms or not support_terms:
        return False
    shared = surface_terms & support_terms
    minimum = max(2, min(4, math.ceil(len(surface_terms) * 0.40)))
    return len(shared) >= minimum


''')
assert s.count(marker) == 1, f'synthesis marker count={s.count(marker)}'
s = s.replace(marker, helper + marker)

old_pol = (
    "    if (\n"
    "        _has_material_negation(surface_casefold) != _has_material_negation(support_casefold)\n"
    "        and shared_terms\n"
    "        and not _has_non_entailment_boundary(surface_casefold)\n"
    "    ):\n"
    "        raise _verification_failure(\n"
    "            \"M26-PA7-ME-056\",\n"
    "            \"claim surface flips factual polarity\",\n"
    "        )\n"
)
new_pol = (
    "    surface_negated = _negation_applies_to_shared_proposition(surface, shared_terms)\n"
    "    support_negated = _negation_applies_to_shared_proposition(support, shared_terms)\n"
    "    if (\n"
    "        surface_negated != support_negated\n"
    "        and shared_terms\n"
    "        and not _has_non_entailment_boundary(surface_casefold)\n"
    "    ):\n"
    "        raise _verification_failure(\n"
    "            \"M26-PA7-ME-056\",\n"
    "            \"claim surface flips factual polarity\",\n"
    "        )\n"
)
assert s.count(old_pol) == 1, f'ME056 anchor count={s.count(old_pol)}'
s = s.replace(old_pol, new_pol)

marker2 = 'def _hard_boundary_entities(text: str) -> set[str]:\n'
helper2 = dedent(r'''
def _negation_applies_to_shared_proposition(text: str, shared_terms: set[str]) -> bool:
    if not shared_terms:
        return False
    threshold = max(1, math.ceil(len(shared_terms) * 0.50))
    clauses = re.split(r"[.!?;]+|\b(?:but|whereas|while)\b", str(text), flags=re.I)
    for clause in clauses:
        if not _has_material_negation(clause.casefold()):
            continue
        clause_terms = _meaningful_terms(clause) - _relevance_common_terms()
        if len(clause_terms & shared_terms) >= threshold:
            return True
    return False


''')
assert s.count(marker2) == 1, f'entity marker count={s.count(marker2)}'
s = s.replace(marker2, helper2 + marker2)
p.write_text(s)
