from schemas.extraction import ExtractedEvent, ExtractedPerson, MemoryExtraction


def test_memory_extraction_preserves_uncertain_introduction_evidence() -> None:
    extraction = MemoryExtraction(
        introduced_person=ExtractedPerson(
            display_name="David",
            relationship_to_patient="neighbor",
            confidence=0.74,
        ),
        events=[
            ExtractedEvent(
                title="Helped with groceries",
                description="David said he helped with groceries yesterday.",
                date_text="yesterday",
                confidence=0.68,
            )
        ],
        claims=["David said he lives next door."],
        needs_caregiver_review=True,
    )

    dumped = extraction.model_dump()

    assert dumped["introduced_person"]["display_name"] == "David"
    assert dumped["introduced_person"]["relationship_to_patient"] == "neighbor"
    assert dumped["events"][0]["date_text"] == "yesterday"
    assert dumped["claims"] == ["David said he lives next door."]
    assert dumped["needs_caregiver_review"] is True
