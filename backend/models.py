# backend/models.py
# Pydantic data models — mirrors src/types/index.ts
#
# All models use snake_case field names with aliases for camelCase JSON
# compatibility with the existing frontend.

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Enums / Literal Types ─────────────────────────────────────────────

HazardType = Literal["low", "moderate", "high"]
FireClass = Literal["A", "B", "C", "D", "F"]
OccupancyGroup = Literal["A", "B", "C", "D", "E", "F", "G", "H", "J", "K"]
OccupancySubdivision = Literal[
    "A-1", "A-2", "A-3", "A-4", "A-5", "A-6",
    "B-1", "B-2",
    "C-1", "C-2", "C-3",
    "D-1", "D-2", "D-3", "D-4", "D-5", "D-6", "D-7",
    "E-1", "E-2", "E-3", "E-4", "E-5",
    "E-I", "E-II",  # NBCS 2026 Part F, Section 3.1.6
    "F-1", "F-2", "F-3",
    "F-I", "F-II",  # NBCS 2026 Part F, Section 3.1.7
    "G-1", "G-2", "G-3",
    "H", "J",
    "K",  # NBCS 2026 Part F, Section 3.1.11 — Mixed Occupancy
]
ConstructionType = Literal["type12", "type34"]
ConfidenceLevel = Literal["high", "medium", "low"]
AnalysisMethod = Literal["structured_input", "ai_vision", "manual_override"]
Grade = Literal["A", "B", "C", "D"]
NOCReadiness = Literal["READY", "CONDITIONAL", "NOT_READY"]


# ── Core Input ─────────────────────────────────────────────────────────


class BuildingInput(BaseModel):
    """Core building data — input to the rule engine."""

    model_config = {"populate_by_name": True}

    building_name: str = Field(alias="buildingName", default="")
    building_type: str = Field(alias="buildingType", default="")
    total_floor_area: float = Field(alias="totalFloorArea", default=0)
    number_of_floors: int = Field(alias="numberOfFloors", default=0)
    floor_areas: list[float] = Field(alias="floorAreas", default_factory=list)
    building_height: float = Field(alias="buildingHeight", default=0)
    occupant_count: int = Field(alias="occupantCount", default=0)
    has_kitchen: bool = Field(alias="hasKitchen", default=False)
    cooking_area_m2: Optional[float] = Field(alias="cookingAreaM2", default=None)
    has_flammable_liquids: bool = Field(alias="hasFlammableLiquids", default=False)
    flammable_liquids_litres: Optional[float] = Field(alias="flammableLiquidsLitres", default=None)
    has_flammable_gases: bool = Field(alias="hasFlammableGases", default=False)
    flammable_gases_litres: Optional[float] = Field(alias="flammableGasesLitres", default=None)
    has_combustible_metals: bool = Field(alias="hasCombustibleMetals", default=False)
    has_electrical_hazards: bool = Field(alias="hasElectricalHazards", default=False)
    state: Optional[str] = None

    # Phase 1 — Building Basics fields (Software Scope Screen 1)
    project_name: str = Field(alias="projectName", default="")
    city: str = Field(alias="city", default="")
    building_status: Optional[str] = Field(
        alias="buildingStatus", default=None,
        description="proposed | existing | under_construction",
    )
    plot_area: Optional[float] = Field(alias="plotArea", default=None, description="Plot area in m²")
    total_built_up_area: Optional[float] = Field(alias="totalBuiltUpArea", default=None, description="Total built-up area in m²")
    basement_count: int = Field(alias="basementCount", default=0, description="Number of basement levels")
    parking_type: Optional[str] = Field(
        alias="parkingType", default=None,
        description="open | stilt | basement | mlcp",
    )
    sprinkler_proposed: Optional[bool] = Field(alias="sprinklerProposed", default=None)

    # NBC 2016 Part IV fields (optional)
    occupancy_group: Optional[OccupancyGroup] = Field(alias="occupancyGroup", default=None)
    occupancy_subdivision: Optional[str] = Field(alias="occupancySubdivision", default=None)
    construction_type: Optional[ConstructionType] = Field(alias="constructionType", default=None)
    has_sprinklers: Optional[bool] = Field(alias="hasSprinklers", default=None)
    travel_distance_m: Optional[float] = Field(alias="travelDistanceM", default=None)
    basement_area: float = Field(alias="basementArea", default=0)

    # NBCS 2026 Part F — additional input fields
    has_ev_parking: bool = Field(
        alias="hasEvParking", default=False,
        description="Whether building has EV parking/charging in podium or basements. "
                    "NBCS 2026 Table 7A Note 3: triggers CL-5 sprinkler protection.",
    )
    dead_end_corridor_m: Optional[float] = Field(
        alias="deadEndCorridorM", default=None,
        description="Longest dead-end corridor length in metres. "
                    "NBCS 2026 Part F, Section 4.4.2.2(c).",
    )

    # Mixed-occupancy structure (NBC Part 4 upgrade)
    occupancy_selection: Optional["OccupancySelection"] = Field(
        alias="occupancySelection", default=None,
        description="Structured single-or-mixed occupancy selection with optional zones.",
    )


# ── Mixed-occupancy models ────────────────────────────────────────────


class OccupancyZone(BaseModel):
    """One occupancy zone within a mixed-occupancy building."""
    model_config = {"populate_by_name": True}

    occupancy_code: str = Field(alias="occupancyCode", description="NBC subdivision code, e.g. 'A-5', 'D-3'.")
    label: str = Field(default="", description="Human-readable label, e.g. 'Hotel', 'Banquet Hall'.")
    floor_range: Optional[str] = Field(alias="floorRange", default=None, description="Floors this zone covers, e.g. 'Ground', '1-3'.")
    area_m2: Optional[float] = Field(alias="areaM2", default=None, description="Area allocated to this zone in m².")


class OccupancySelection(BaseModel):
    """Structured single-or-mixed occupancy selection."""
    model_config = {"populate_by_name": True}

    mode: Literal["single", "mixed"] = Field(default="single")
    primary_occupancy: Optional[str] = Field(alias="primaryOccupancy", default=None)
    secondary_occupancies: list[str] = Field(alias="secondaryOccupancies", default_factory=list)
    occupancy_zones: list[OccupancyZone] = Field(alias="occupancyZones", default_factory=list)


# ── Normalised compliance-result item (safety-calc-india style) ───────


ComplianceStatus = Literal["required", "not_required", "conditional", "insufficient_data"]


class ComplianceResultItem(BaseModel):
    """Normalised output for a single compliance check (system / rule).

    This is the safety-calc-india style output used in UI tables and PDF
    reports. Every fire-system check (wet riser, down comer, sprinkler, …)
    is emitted as one ComplianceResultItem.
    """
    model_config = {"populate_by_name": True}

    id: str = Field(description="Machine-readable id, e.g. 'wet_riser'.")
    title: str = Field(description="Display title, e.g. 'Wet Riser'.")
    status: ComplianceStatus = Field(default="not_required")
    reason: str = Field(default="", description="Human-readable reason.")
    clause_refs: list[str] = Field(alias="clauseRefs", default_factory=list)
    triggered_by: list[str] = Field(alias="triggeredBy", default_factory=list, description="Occupancy codes that required this system.")
    bis_standards: list[str] = Field(alias="bisStandards", default_factory=list)
    input_dependencies: list[str] = Field(alias="inputDependencies", default_factory=list)
    missing_inputs: list[str] = Field(alias="missingInputs", default_factory=list)
    next_steps: list[str] = Field(alias="nextSteps", default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MixedOccupancySummary(BaseModel):
    """Summary of the aggregated mixed-occupancy resolution."""
    model_config = {"populate_by_name": True}

    mode: str = Field(default="single")
    occupancy_codes: list[str] = Field(alias="occupancyCodes", default_factory=list)
    occupancy_labels: dict[str, str] = Field(alias="occupancyLabels", default_factory=dict)
    height_tier_labels: dict[str, str] = Field(alias="heightTierLabels", default_factory=dict)


class AggregatedQuantity(BaseModel):
    """Aggregated numeric requirement (e.g. tank litres, pump LPM)."""
    model_config = {"populate_by_name": True}

    value: int
    unit: str = Field(default="")
    triggered_by: list[str] = Field(alias="triggeredBy", default_factory=list)


# ── Rule Engine Output Models ──────────────────────────────────────────


class ExtinguisherRequirement(BaseModel):
    model_config = {"populate_by_name": True}

    fire_class: FireClass = Field(alias="fireClass")
    minimum_rating: str = Field(alias="minimumRating")
    count_required: int = Field(alias="countRequired")
    per_floor: Optional[bool] = Field(alias="perFloor", default=None)
    clause_ref: str = Field(alias="clauseRef")
    note: Optional[str] = None


class Violation(BaseModel):
    model_config = {"populate_by_name": True}

    rule_id: str = Field(alias="ruleId")
    clause_ref: str = Field(alias="clauseRef")
    severity: Literal["high", "medium", "low"]
    description: str
    fix_suggestion: str = Field(alias="fixSuggestion")
    floor: Optional[str] = None


# ── NBC Compliance Detail ──────────────────────────────────────────────


class EvaluatedNote(BaseModel):
    """A Table 7 note that has been evaluated against actual building inputs."""
    model_config = {"populate_by_name": True}

    note_id: int = Field(alias="noteId")
    field: Optional[str] = Field(default=None, description="Which installation field this note applies to, e.g. 'automaticSprinkler'")
    condition: str = Field(description="Machine-readable condition key, e.g. 'basement_area_gt_200'")
    is_met: bool = Field(alias="isMet", description="Whether the condition is satisfied by the building inputs")
    description: str = Field(description="Full text of the note from NBC 2016")
    additional_value: Optional[float] = Field(alias="additionalValue", default=None, description="Extra value to add when condition is met (e.g. +5000 litres)")
    set_value: Optional[float] = Field(alias="setValue", default=None, description="Direct value to assign when condition is met (e.g. pump capacity in LPM)")


class FirefightingInstallationRequirement(BaseModel):
    model_config = {"populate_by_name": True}

    fire_extinguisher: bool = Field(alias="fireExtinguisher")
    first_aid_hose_reel: bool = Field(alias="firstAidHoseReel")
    wet_riser: bool = Field(alias="wetRiser")
    down_comer: bool = Field(alias="downComer")
    yard_hydrant: bool = Field(alias="yardHydrant")
    automatic_sprinkler: bool = Field(alias="automaticSprinkler")
    manual_fire_alarm: bool = Field(alias="manualFireAlarm")
    auto_detection_alarm: bool = Field(alias="autoDetectionAlarm")
    # NBCS 2026 Part F Tables 7A–7J, Column 10 — new requirement
    public_address_voice_evacuation: bool = Field(
        alias="publicAddressVoiceEvacuation", default=False,
        description="Public Address and Voice Evacuation System. "
                    "NBCS 2026 Part F Tables 7A–7J, Column 10.",
    )
    underground_tank_litres: Optional[int] = Field(alias="undergroundTankLitres", default=None)
    terrace_tank_litres: Optional[int] = Field(alias="terraceTankLitres", default=None)
    underground_pump_lpm: Optional[int] = Field(alias="undergroundPumpLpm", default=None)
    terrace_pump_lpm: Optional[int] = Field(alias="terracePumpLpm", default=None)
    height_tier_label: str = Field(alias="heightTierLabel")
    occupancy_label: str = Field(alias="occupancyLabel")
    clause_ref: str = Field(alias="clauseRef")
    notes: Optional[str] = Field(default=None)
    evaluated_notes: list[EvaluatedNote] = Field(alias="evaluatedNotes", default_factory=list)


class FloorOccupantLoad(BaseModel):
    """Occupant load for a single floor."""
    model_config = {"populate_by_name": True}

    floor_index: int = Field(alias="floorIndex", description="0-based floor index (0 = ground)")
    floor_label: str = Field(alias="floorLabel", description="Human-readable floor name, e.g. 'Ground Floor', 'Floor 1'")
    floor_area: float = Field(alias="floorArea", description="Area of this floor in m²")
    occupant_count: int = Field(alias="occupantCount", description="Calculated occupants for this floor")


class OccupantLoadData(BaseModel):
    model_config = {"populate_by_name": True}

    total_occupants: int = Field(alias="totalOccupants", description="Sum of occupants across all floors")
    max_occupants: int = Field(alias="maxOccupants", description="Max occupants on any single floor (for rule checks)")
    load_factor: float = Field(alias="loadFactor")
    floor_area_used: float = Field(alias="floorAreaUsed", description="Total floor area used")
    group: OccupancyGroup
    floor_wise: list[FloorOccupantLoad] = Field(alias="floorWise", default_factory=list)


class FloorExitCapacity(BaseModel):
    """Exit width requirements for a single floor."""
    model_config = {"populate_by_name": True}

    floor_index: int = Field(alias="floorIndex")
    floor_label: str = Field(alias="floorLabel")
    occupant_count: int = Field(alias="occupantCount", description="Occupants on this floor")
    stairway_width_mm: float = Field(alias="stairwayWidthMm", description="Required stairway width in mm")
    level_width_mm: float = Field(alias="levelWidthMm", description="Required door/corridor/ramp width in mm")


class ExitCapacityData(BaseModel):
    model_config = {"populate_by_name": True}

    stairway_mm_per_person: float = Field(alias="stairwayMmPerPerson", description="NBC Table 4 factor")
    level_mm_per_person: float = Field(alias="levelMmPerPerson", description="NBC Table 4 factor")
    max_stairway_width_mm: float = Field(alias="maxStairwayWidthMm", description="Widest stairway required (max floor)")
    max_level_width_mm: float = Field(alias="maxLevelWidthMm", description="Widest door/corridor required (max floor)")
    total_occupant_count: int = Field(alias="totalOccupantCount")
    group: OccupancyGroup
    floor_wise: list[FloorExitCapacity] = Field(alias="floorWise", default_factory=list)


class TravelDistanceData(BaseModel):
    model_config = {"populate_by_name": True}

    max_distance_m: float = Field(alias="maxDistanceM")
    base_distance_m: float = Field(alias="baseDistanceM")
    sprinkler_applied: bool = Field(alias="sprinklerApplied")
    construction_type: ConstructionType = Field(alias="constructionType")
    group: OccupancyGroup


class FloorDetectorCount(BaseModel):
    """Sprinkler and smoke detector count for a single floor."""
    model_config = {"populate_by_name": True}

    floor_index: int = Field(alias="floorIndex")
    floor_label: str = Field(alias="floorLabel")
    floor_area: float = Field(alias="floorArea", description="Floor area in m²")
    sprinkler_count: int = Field(alias="sprinklerCount")
    smoke_detector_count: int = Field(alias="smokeDetectorCount")


class DetectorCountData(BaseModel):
    """Sprinkler and smoke detector counts — total and floor-wise."""
    model_config = {"populate_by_name": True}

    total_sprinklers: int = Field(alias="totalSprinklers")
    total_smoke_detectors: int = Field(alias="totalSmokeDetectors")
    sprinkler_spacing_m: float = Field(alias="sprinklerSpacingM", default=2.8)
    smoke_detector_spacing_m: float = Field(alias="smokeDetectorSpacingM", default=5.0)
    sprinkler_coverage_m2: float = Field(alias="sprinklerCoverageM2", description="Coverage area per sprinkler")
    smoke_detector_coverage_m2: float = Field(alias="smokeDetectorCoverageM2", description="Coverage area per detector")
    floor_wise: list[FloorDetectorCount] = Field(alias="floorWise", default_factory=list)


# ── NBCS 2026 Applicability & Tracking ─────────────────────────────────


class NBCSOccupantLoadData(BaseModel):
    model_config = {"populate_by_name": True}

    total_occupants: int = Field(alias="totalOccupants", description="NBCS calculated occupants")
    load_factor_net: Optional[float] = Field(alias="loadFactorNet", default=None)
    load_factor_gross: Optional[float] = Field(alias="loadFactorGross", default=None)
    note: str = Field(alias="note", default="Based on NBCS 2026 Table 2")


class NBCSExitCapacityData(BaseModel):
    model_config = {"populate_by_name": True}

    stairway_mm_per_person: float = Field(alias="stairwayMmPerPerson")
    level_mm_per_person: float = Field(alias="levelMmPerPerson")
    max_stairway_width_mm: float = Field(alias="maxStairwayWidthMm")
    max_level_width_mm: float = Field(alias="maxLevelWidthMm")
    dead_end_limit_m: float = Field(alias="deadEndLimitM")
    note: str = Field(alias="note", default="Based on NBCS 2026 Table 3")


class NBCSTravelDistanceData(BaseModel):
    model_config = {"populate_by_name": True}

    max_distance_m: Optional[float] = Field(alias="maxDistanceM")
    note: str = Field(alias="note", default="Based on NBCS 2026 Table 4")


class NBCSApplicabilityResult(BaseModel):
    """Result of NBCS 2026 Part F Section 1.2 applicability check."""
    model_config = {"populate_by_name": True}

    is_applicable: bool = Field(alias="isApplicable", description="Whether NBCS Part F provisions apply")
    reason: str = Field(description="Human-readable explanation")
    clause_ref: str = Field(alias="clauseRef", description="NBCS section reference")
    occupancy_label: str = Field(alias="occupancyLabel", description="Display name of the occupancy")
    height_threshold_m: Optional[float] = Field(alias="heightThresholdM", default=None)
    area_threshold_m2: Optional[float] = Field(alias="areaThresholdM2", default=None)


# NBCS 2026 Part F — Protection Level Labels
# Ref: Tables 7A–7J tier definitions
NBCSProtectionLevel = Literal["HL-1", "HL-2", "HL-3", "CL-3", "CL-4", "CL-5", "SELF-CERT"]


class NBCSFirefightingInstallationRequirement(BaseModel):
    """NBCS 2026 Part F Tables 7A–7J tracking result.

    This is a TRACKING model — it runs in parallel with NBC 2016
    firefighting installation requirements but does NOT replace them.

    Software Scope reference:
      "FireRuleX should support both a baseline NBC 2016 library and
       an NBCS tracking layer, but should not switch live calculation
       logic to NBCS nationally until the applicable state or
       approving authority clearly adopts and enforces it."
    """

    model_config = {"populate_by_name": True}

    # Core installation R/NR flags (mirrors NBC 2016 but from NBCS tables)
    fire_extinguisher: bool = Field(alias="fireExtinguisher")
    first_aid_hose_reel: bool = Field(alias="firstAidHoseReel")
    wet_riser: bool = Field(alias="wetRiser")
    down_comer: bool = Field(alias="downComer")
    yard_hydrant: bool = Field(alias="yardHydrant")
    automatic_sprinkler: bool = Field(alias="automaticSprinkler")
    auto_detection_alarm: bool = Field(alias="autoDetectionAlarm")
    # New in NBCS 2026 — Column 10 of Tables 7A–7J
    public_address_voice_evacuation: bool = Field(
        alias="publicAddressVoiceEvacuation",
        description="NBCS 2026 Tables 7A–7J, Column 10.",
    )

    # NBCS-specific metadata
    protection_level: NBCSProtectionLevel = Field(
        alias="protectionLevel",
        description="NBCS protection tier label (HL-1/HL-2/HL-3/CL-3/CL-4/CL-5).",
    )
    nbcs_table_ref: str = Field(
        alias="nbcsTableRef",
        description="Specific NBCS table reference (e.g. 'Table 7A', 'Table 7E').",
    )
    occupancy_label: str = Field(alias="occupancyLabel")
    clause_ref: str = Field(alias="clauseRef")
    self_certification_eligible: bool = Field(
        alias="selfCertificationEligible", default=False,
        description="True if building falls within the self-certification threshold "
                    "(≤500 m² and ≤15/24m height, per NBCS table header).",
    )
    triggered_notes: list[str] = Field(
        alias="triggeredNotes", default_factory=list,
        description="Active conditional notes (e.g. 'Note 1: Kitchen upgrades to HL-2').",
    )
    differs_from_nbc: bool = Field(
        alias="differsFromNbc", default=False,
        description="True if NBCS requirements differ from active NBC 2016 requirements.",
    )


class NBCComplianceData(BaseModel):
    model_config = {"populate_by_name": True}

    occupant_load: Optional[OccupantLoadData] = Field(alias="occupantLoad", default=None)
    exit_capacity: Optional[ExitCapacityData] = Field(alias="exitCapacity", default=None)
    travel_distance: Optional[TravelDistanceData] = Field(alias="travelDistance", default=None)
    firefighting_installations: Optional[FirefightingInstallationRequirement] = Field(
        alias="firefightingInstallations", default=None
    )
    detector_counts: Optional[DetectorCountData] = Field(alias="detectorCounts", default=None)
    nbcs_applicability: Optional[NBCSApplicabilityResult] = Field(alias="nbcsApplicability", default=None)
    nbcs_firefighting_installations: Optional["NBCSFirefightingInstallationRequirement"] = Field(
        alias="nbcsFirefightingInstallations", default=None,
        description="NBCS 2026 Part F Tables 7A–7J tracking result (parallel to NBC 2016).",
    )
    nbcs_occupant_load: Optional[NBCSOccupantLoadData] = Field(alias="nbcsOccupantLoad", default=None)
    nbcs_exit_capacity: Optional[NBCSExitCapacityData] = Field(alias="nbcsExitCapacity", default=None)
    nbcs_travel_distance: Optional[NBCSTravelDistanceData] = Field(alias="nbcsTravelDistance", default=None)


class SystemCard(BaseModel):
    model_config = {"populate_by_name": True}

    system_name: str = Field(alias="systemName")
    status: str = Field(description="e.g. 'REQUIRED', 'NOT REQUIRED'")
    triggered_by: str = Field(alias="triggeredBy")
    relevant_standards: list[str] = Field(alias="relevantStandards")
    missing_inputs: list[str] = Field(alias="missingInputs", default_factory=list)
    next_steps: list[str] = Field(alias="nextSteps", default_factory=list)


class AnalysisResult(BaseModel):
    model_config = {"populate_by_name": True}

    hazard_type: HazardType = Field(alias="hazardType")
    compliance_score: int = Field(alias="complianceScore")
    grade: Grade
    noc_readiness: NOCReadiness = Field(alias="nocReadiness")
    required_extinguishers: list[ExtinguisherRequirement] = Field(alias="requiredExtinguishers")
    violations: list[Violation]
    passed_rules: list[str] = Field(alias="passedRules")
    analysis_method: AnalysisMethod = Field(alias="analysisMethod")
    nbc_compliance: Optional[NBCComplianceData] = Field(alias="nbcCompliance", default=None)
    system_cards: list[SystemCard] = Field(alias="systemCards", default_factory=list)

    # Normalised safety-calc-india style output (NEW)
    compliance_items: list[ComplianceResultItem] = Field(alias="complianceItems", default_factory=list)
    aggregated_quantities: dict[str, AggregatedQuantity] = Field(alias="aggregatedQuantities", default_factory=dict)
    mixed_occupancy_summary: Optional[MixedOccupancySummary] = Field(alias="mixedOccupancySummary", default=None)
    passed_checks: list[str] = Field(alias="passedChecks", default_factory=list)
    missing_inputs: list[str] = Field(alias="missingInputs", default_factory=list)
    next_steps: list[str] = Field(alias="nextSteps", default_factory=list)


# ── Extraction & API Response ──────────────────────────────────────────


class ExtractionConfidence(BaseModel):
    overall: ConfidenceLevel
    score: int
    flags: list[str]


class AnalyzeMeta(BaseModel):
    model_config = {"populate_by_name": True}

    file_name: str = Field(alias="fileName")
    file_size: int = Field(alias="fileSize")
    file_type: str = Field(alias="fileType")
    original_format: str = Field(alias="originalFormat")
    was_converted: bool = Field(alias="wasConverted")
    ai_provider: str = Field(alias="aiProvider")
    analyzed_at: str = Field(alias="analyzedAt")


class AnalyzeResponse(BaseModel):
    model_config = {"populate_by_name": True}

    extraction: BuildingInput
    analysis: AnalysisResult
    confidence: ExtractionConfidence
    needs_confirmation: bool = Field(alias="needsConfirmation")
    meta: AnalyzeMeta


# ── Phase 3a — Automated Equipment Placement ───────────────────────────


class ScaleCalibrationData(BaseModel):
    """Drawing scale, cross-referenced from printed dimension text vs
    geometry. Always editable — never silently applied (see
    plan_extractor/placement/scale_calibration.py)."""
    model_config = {"populate_by_name": True}

    mm_per_pt: Optional[float] = Field(alias="mmPerPt", default=None)
    confidence: str  # "green" | "amber" | "red"
    sample_count: int = Field(alias="sampleCount", default=0)
    rejected_samples: int = Field(alias="rejectedSamples", default=0)
    note: str = ""
    editable: bool = True


class PlacementPointData(BaseModel):
    """One suggested fire-extinguisher location, in PDF point space (x, y
    from the top of the page) so the frontend can position it directly on
    a canvas-rendered page at the same coordinate system as the source PDF."""
    model_config = {"populate_by_name": True}

    index: int
    x_pt: float = Field(alias="xPt")
    y_pt: float = Field(alias="yPt")
    is_junction: bool = Field(alias="isJunction", description="True if this is a corridor/circulation point")
    location_description: str = Field(alias="locationDescription", default="")
    clause_ref: str = Field(alias="clauseRef", default="")


class PlacementSuggestionResponse(BaseModel):
    """Response for POST /api/placement/suggest."""
    model_config = {"populate_by_name": True}

    page_index: int = Field(alias="pageIndex")
    page_width_pt: float = Field(alias="pageWidthPt")
    page_height_pt: float = Field(alias="pageHeightPt")
    hazard_type: str = Field(alias="hazardType")
    rating: str
    max_area_m2: float = Field(alias="maxAreaM2")
    coverage_radius_m: float = Field(alias="coverageRadiusM")
    scale: ScaleCalibrationData
    points: list[PlacementPointData] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
