// src/types/index.ts
// Core TypeScript types for the FireRuleX rule engine

export type HazardType = 'low' | 'moderate' | 'high';
export type FireClass = 'A' | 'B' | 'C' | 'D' | 'F';

export type OccupancyGroup = 'A' | 'B' | 'C' | 'D' | 'E' | 'F' | 'G' | 'H' | 'J' | 'K';

export type OccupancySubdivision =
    | 'A-1' | 'A-2' | 'A-3' | 'A-4' | 'A-5' | 'A-6'
    | 'B-1' | 'B-2'
    | 'C-1' | 'C-2' | 'C-3'
    | 'D-1' | 'D-2' | 'D-3' | 'D-4' | 'D-5' | 'D-6' | 'D-7'
    | 'E-1' | 'E-2' | 'E-3' | 'E-4' | 'E-5'
    | 'E-I' | 'E-II'
    | 'F-1' | 'F-2' | 'F-3'
    | 'F-I' | 'F-II'
    | 'G-1' | 'G-2' | 'G-3'
    | 'H' | 'J' | 'K';

export type ConstructionType = 'type12' | 'type34';
export type ComplianceStatus = 'required' | 'not_required' | 'conditional' | 'insufficient_data';

// ── Mixed-occupancy input ────────────────────────────────────────

export interface OccupancyZone {
    occupancyCode: string;
    label?: string;
    floorRange?: string;
    areaM2?: number;
}

export interface OccupancySelection {
    mode: 'single' | 'mixed';
    primaryOccupancy?: string;
    secondaryOccupancies: string[];
    occupancyZones: OccupancyZone[];
}

// ── Normalised compliance-result item ────────────────────────────

export interface ComplianceResultItem {
    id: string;
    title: string;
    status: ComplianceStatus;
    reason: string;
    clauseRefs: string[];
    triggeredBy: string[];
    bisStandards: string[];
    inputDependencies?: string[];
    missingInputs?: string[];
    nextSteps: string[];
    notes: string[];
}

export interface MixedOccupancySummary {
    mode: string;
    occupancyCodes: string[];
    occupancyLabels: Record<string, string>;
    heightTierLabels: Record<string, string>;
}

export interface AggregatedQuantity {
    value: number;
    unit: string;
    triggeredBy: string[];
}

// ── Occupancy catalogue (from GET /api/occupancies) ──────────────

export interface OccupancyGroupInfo {
    group: string;
    label: string;
    description: string;
    subdivisions: Array<{
        code: string;
        label: string;
        description?: string;
        examples?: string[];
    }>;
}

// ── Legacy types (kept for backward-compat with existing pages) ──

export interface BuildingInput {
    buildingName: string;
    buildingType: string;
    totalFloorArea: number;
    numberOfFloors: number;
    floorAreas: number[];
    buildingHeight: number;
    occupantCount: number;
    hasKitchen: boolean;
    cookingAreaM2?: number;
    hasFlammableLiquids: boolean;
    flammableLiquidsLitres?: number;
    hasFlammableGases: boolean;
    flammableGasesLitres?: number;
    hasCombustibleMetals: boolean;
    hasElectricalHazards: boolean;
    state?: string;
    projectName?: string;
    city?: string;
    buildingStatus?: 'proposed' | 'existing' | 'under_construction';
    plotArea?: number;
    totalBuiltUpArea?: number;
    basementCount?: number;
    parkingType?: 'open' | 'stilt' | 'basement' | 'mlcp';
    sprinklerProposed?: boolean;
    hasEvParking?: boolean;
    deadEndCorridorM?: number;
    occupancyGroup?: OccupancyGroup;
    occupancySubdivision?: OccupancySubdivision;
    constructionType?: ConstructionType;
    hasSprinklers?: boolean;
    travelDistanceM?: number;
    basementArea?: number;
    occupancySelection?: OccupancySelection;
}

export interface ExtinguisherRequirement {
    fireClass: FireClass;
    minimumRating: string;
    countRequired: number;
    perFloor?: boolean;
    clauseRef: string;
    note?: string;
}

export interface Violation {
    ruleId: string;
    clauseRef: string;
    severity: 'high' | 'medium' | 'low';
    description: string;
    fixSuggestion: string;
    floor?: string;
}

export interface EvaluatedNote {
    noteId: number;
    field?: string;
    condition: string;
    isMet: boolean;
    description: string;
    additionalValue?: number;
    setValue?: number;
}

export interface FirefightingInstallationRequirement {
    fireExtinguisher: boolean;
    firstAidHoseReel: boolean;
    wetRiser: boolean;
    downComer: boolean;
    yardHydrant: boolean;
    automaticSprinkler: boolean;
    manualFireAlarm: boolean;
    autoDetectionAlarm: boolean;
    publicAddressVoiceEvacuation: boolean;
    undergroundTankLitres: number | null;
    terraceTankLitres: number | null;
    undergroundPumpLpm: number | null;
    terracePumpLpm: number | null;
    heightTierLabel: string;
    occupancyLabel: string;
    clauseRef: string;
    notes?: string;
    evaluatedNotes?: EvaluatedNote[];
}

export interface FloorOccupantLoad {
    floorIndex: number;
    floorLabel: string;
    floorArea: number;
    occupantCount: number;
}

export interface FloorExitCapacity {
    floorIndex: number;
    floorLabel: string;
    occupantCount: number;
    stairwayWidthMm: number;
    levelWidthMm: number;
}

export interface FloorDetectorCount {
    floorIndex: number;
    floorLabel: string;
    floorArea: number;
    sprinklerCount: number;
    smokeDetectorCount: number;
}

export interface DetectorCountData {
    totalSprinklers: number;
    totalSmokeDetectors: number;
    sprinklerSpacingM: number;
    smokeDetectorSpacingM: number;
    sprinklerCoverageM2: number;
    smokeDetectorCoverageM2: number;
    floorWise: FloorDetectorCount[];
}

export interface NBCSApplicabilityData {
    isApplicable: boolean;
    reason: string;
    occupancyLabel: string;
    clauseRef: string;
}

export interface PlacementPoint {
    index: number;
    xPt: number;
    yPt: number;
    isJunction: boolean;
    locationDescription: string;
    clauseRef: string;
}

export interface PlacementScale {
    mm_per_pt: number | null;
    confidence: 'green' | 'amber' | 'red';
    sample_count: number;
    rejected_samples: number;
    note: string;
    editable: boolean;
}

export interface PlacementFloorResult {
    floorIndex: number;
    floorLabel: string;
    pageIndex: number;
    pageWidthPt: number;
    pageHeightPt: number;
    hazardType: string;
    rating: string;
    maxAreaM2: number;
    coverageRadiusM: number;
    scale: PlacementScale;
    points: PlacementPoint[];
    warnings: string[];
}

export interface PlacementSuggestFloorsResponse {
    floors: PlacementFloorResult[];
    warnings: string[];
}

export interface NBCSOccupantLoadData {
    note: string;
    totalOccupants: number;
    loadFactorNet?: number | null;
    loadFactorGross?: number | null;
}

export interface NBCSExitCapacityData {
    note: string;
    stairwayMmPerPerson: number;
    levelMmPerPerson: number;
    maxStairwayWidthMm: number;
    maxLevelWidthMm: number;
    deadEndLimitM?: number | null;
}

export interface NBCSTravelDistanceData {
    note: string;
    maxDistanceM: number | null;
}

export interface NBCSFirefightingInstallationsData {
    note: string;
    nbcsTableRef: string;
    protectionLevel: string;
    differsFromNbc: boolean;
    fireExtinguisher: boolean;
    firstAidHoseReel: boolean;
    wetRiser: boolean;
    downComer: boolean;
    yardHydrant: boolean;
    automaticSprinkler: boolean;
    autoDetectionAlarm: boolean;
    publicAddressVoiceEvacuation: boolean;
    triggeredNotes?: string[];
}

export interface NBCComplianceData {
    occupantLoad?: {
        totalOccupants: number;
        maxOccupants: number;
        loadFactor: number;
        floorAreaUsed: number;
        group: OccupancyGroup;
        floorWise: FloorOccupantLoad[];
    };
    exitCapacity?: {
        stairwayMmPerPerson: number;
        levelMmPerPerson: number;
        maxStairwayWidthMm: number;
        maxLevelWidthMm: number;
        totalOccupantCount: number;
        group: OccupancyGroup;
        floorWise: FloorExitCapacity[];
    };
    travelDistance?: {
        maxDistanceM: number;
        baseDistanceM: number;
        sprinklerApplied: boolean;
        constructionType: ConstructionType;
        group: OccupancyGroup;
    };
    firefightingInstallations?: FirefightingInstallationRequirement;
    detectorCounts?: DetectorCountData;
    nbcsApplicability?: NBCSApplicabilityData;
    nbcsOccupantLoad?: NBCSOccupantLoadData;
    nbcsExitCapacity?: NBCSExitCapacityData;
    nbcsTravelDistance?: NBCSTravelDistanceData;
    nbcsFirefightingInstallations?: NBCSFirefightingInstallationsData;
}

export interface SystemCard {
    systemName: string;
    status: string;
    triggeredBy: string;
    relevantStandards: string[];
    missingInputs: string[];
    nextSteps: string[];
}

export interface AnalysisResult {
    hazardType: HazardType;
    complianceScore: number;
    grade: 'A' | 'B' | 'C' | 'D';
    nocReadiness: 'READY' | 'CONDITIONAL' | 'NOT_READY';
    requiredExtinguishers: ExtinguisherRequirement[];
    violations: Violation[];
    passedRules: string[];
    analysisMethod: 'structured_input' | 'ai_vision' | 'manual_override';
    nbcCompliance?: NBCComplianceData;
    systemCards?: SystemCard[];
    complianceItems?: ComplianceResultItem[];
    aggregatedQuantities?: Record<string, AggregatedQuantity>;
    mixedOccupancySummary?: MixedOccupancySummary;
    passedChecks?: string[];
    missingInputs?: string[];
    nextSteps?: string[];
}

export type ConfidenceLevel = 'high' | 'medium' | 'low';

export interface ExtractionConfidence {
    overall: ConfidenceLevel;
    score: number;
    flags: string[];
}

export interface AnalyzeResponse {
    extraction: BuildingInput;
    analysis: AnalysisResult;
    confidence: ExtractionConfidence;
    needsConfirmation: boolean;
    meta: {
        fileName: string;
        fileSize: number;
        fileType: string;
        originalFormat: string;
        wasConverted: boolean;
        aiProvider: string;
        analyzedAt: string;
    };
}
