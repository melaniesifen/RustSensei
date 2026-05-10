from rust_sensei.domain.enums import RustLevel


def starting_concept_for_level(level: RustLevel) -> str:
    return {
        RustLevel.NEW: "cargo_hello_world",
        RustLevel.BEGINNER: "variables_primitive_types",
        RustLevel.INTERMEDIATE: "ownership_borrowing_intro",
        RustLevel.PROFICIENT: "traits_generics_testing",
        RustLevel.EXPERT: "advanced_design_review",
    }[level]
