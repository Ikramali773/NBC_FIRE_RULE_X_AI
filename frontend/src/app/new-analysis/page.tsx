'use client';

import { useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';

/* ─── Types ─── */
interface FieldData {
    value: string | number | boolean | null;
    confidence: 'green' | 'amber' | 'red';
    source_stage?: string;
    note?: string;
    proposed_code?: string;
}

interface FloorArea {
    floor_label: string;
    value: number | null;
    confidence: 'green' | 'amber' | 'red';
    source_stage?: string;
}

interface ScaleData {
    value: string | null;
    unit?: string | null;
    confidence: 'green' | 'amber' | 'red';
    source?: string;
    note?: string;
}

interface ExtractionQuality {
    green_fields: number;
    amber_fields: number;
    red_fields: number;
    total_fields: number;
    quality_score: number;
    summary: string;
}

interface ExtractionData {
    source_file_type: string;
    project_name: FieldData;
    city: FieldData;
    state: FieldData;
    building_status: FieldData;
    primary_occupancy_hint: FieldData;
    height_m: FieldData;
    floors_count: FieldData;
    construction_type: FieldData;
    per_floor_areas_m2: FloorArea[];
    basement_area_m2: FieldData;
    basement_levels: FieldData;
    kitchen_present: FieldData;
    sprinklers_proposed: FieldData;
    detected_scale: ScaleData;
    raw_text_labels?: string[];
    warnings?: string[];
    _extraction_quality?: ExtractionQuality;
}

/* ─── Confidence colors ─── */
const CONF_COLORS = {
    green: { bg: '#E8F5E9', border: '#4CAF50', text: '#2E7D32', dot: '#4CAF50' },
    amber: { bg: '#FFF8E1', border: '#FFB300', text: '#F57F17', dot: '#FFB300' },
    red: { bg: '#FFEBEE', border: '#E53935', text: '#C62828', dot: '#E53935' },
};

const CONF_LABELS = { green: 'High', amber: 'Medium', red: 'Low' };

/* ─── Main Page Component ─── */
export default function NewAnalysisPage() {
    const router = useRouter();
    const [step, setStep] = useState<'choose' | 'upload' | 'processing' | 'review' | 'error'>('choose');
    const [file, setFile] = useState<File | null>(null);
    const [error, setError] = useState<string>('');
    const [extractionData, setExtractionData] = useState<ExtractionData | null>(null);
    const [editedData, setEditedData] = useState<Record<string, string | number | boolean | null>>({});
    const [processingStep, setProcessingStep] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const [dragOver, setDragOver] = useState(false);

    const processingSteps = [
        '📤 Reading your building plan...',
        '🔍 Extracting text and geometry...',
        '🏗️ Identifying building parameters...',
        '📋 Mapping to compliance fields...',
    ];

    /* ─── File handling ─── */
    const handleFile = useCallback((f: File) => {
        const ext = f.name.toLowerCase().split('.').pop();
        if (ext !== 'pdf' && ext !== 'dwg') {
            setError(`Unsupported file type '.${ext}'. Only .pdf and .dwg files are accepted.`);
            setStep('error');
            return;
        }
        if (f.size > 20 * 1024 * 1024) {
            setError(`File too large (${(f.size / 1024 / 1024).toFixed(1)}MB). Maximum is 20MB.`);
            setStep('error');
            return;
        }
        setFile(f);
        setError('');
        uploadFile(f);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setDragOver(false);
        if (e.dataTransfer.files?.length > 0) {
            handleFile(e.dataTransfer.files[0]);
        }
    }, [handleFile]);

    /* ─── Upload & extract ─── */
    const uploadFile = async (f: File) => {
        setStep('processing');
        setProcessingStep(0);
        setError('');

        const timers = [
            setTimeout(() => setProcessingStep(1), 1500),
            setTimeout(() => setProcessingStep(2), 4000),
            setTimeout(() => setProcessingStep(3), 8000),
        ];

        try {
            const formData = new FormData();
            formData.append('file', f);

            let API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
            if (API_URL && !API_URL.startsWith('http')) {
                API_URL = `https://${API_URL}`;
            }
            const response = await fetch(`${API_URL}/api/extract`, {
                method: 'POST',
                body: formData,
                signal: AbortSignal.timeout(180000),
            });

            timers.forEach(clearTimeout);

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.error || 'Extraction failed.');
            }

            setExtractionData(data.data);
            // Initialize editable values from extraction
            const edits: Record<string, string | number | boolean | null> = {};
            const d = data.data;
            edits.project_name = d.project_name?.value ?? '';
            edits.city = d.city?.value ?? '';
            edits.state = d.state?.value ?? '';
            edits.height_m = d.height_m?.value ?? '';
            edits.floors_count = d.floors_count?.value ?? '';
            edits.basement_area_m2 = d.basement_area_m2?.value ?? '';
            edits.basement_levels = d.basement_levels?.value ?? '';
            edits.kitchen_present = d.kitchen_present?.value ?? false;
            edits.sprinklers_proposed = d.sprinklers_proposed?.value ?? false;
            setEditedData(edits);
            setStep('review');
        } catch (err) {
            timers.forEach(clearTimeout);
            const msg = err instanceof Error ? err.message : 'Extraction failed.';
            setError(msg);
            setStep('error');
        }
    };

    /* ─── Confirm & navigate to form ─── */
    const confirmAndContinue = () => {
        if (!extractionData) return;

        // Build the prefill data using edited values
        const prefill: Record<string, unknown> = {
            _source: 'extraction',
            _extraction_quality: extractionData._extraction_quality,
            _confidence: {} as Record<string, string>,
        };

        const conf = prefill._confidence as Record<string, string>;

        // Map edited values to form field keys
        prefill.projectName = editedData.project_name || extractionData.project_name?.value || '';
        conf.projectName = extractionData.project_name?.confidence || 'red';

        prefill.city = editedData.city || extractionData.city?.value || '';
        conf.city = extractionData.city?.confidence || 'red';

        prefill.state = editedData.state || extractionData.state?.value || '';
        conf.state = extractionData.state?.confidence || 'red';

        // building_status — always red/null, don't prefill
        conf.buildingStatus = 'red';

        // Height
        const h = editedData.height_m;
        prefill.buildingHeight = h !== '' && h !== null ? Number(h) : 0;
        conf.buildingHeight = extractionData.height_m?.confidence || 'red';

        // Floors
        const f = editedData.floors_count;
        prefill.numberOfFloors = f !== '' && f !== null ? Number(f) : 1;
        conf.numberOfFloors = extractionData.floors_count?.confidence || 'red';

        // Floor areas
        const areas = extractionData.per_floor_areas_m2 || [];
        const floorCount = Number(prefill.numberOfFloors) || 1;
        const floorAreas: number[] = [];
        for (let i = 0; i < floorCount; i++) {
            const areaItem = areas[i];
            floorAreas.push(areaItem?.value || 0);
        }
        prefill.floorAreas = floorAreas;

        // Construction type
        const ct = extractionData.construction_type?.value;
        if (ct === 'type12' || ct === 'type34') {
            prefill.constructionType = ct;
            conf.constructionType = extractionData.construction_type?.confidence || 'red';
        }

        // Basement
        const ba = editedData.basement_area_m2;
        prefill.basementArea = ba !== '' && ba !== null ? Number(ba) : 0;
        conf.basementArea = extractionData.basement_area_m2?.confidence || 'red';

        const bl = editedData.basement_levels;
        prefill.basementCount = bl !== '' && bl !== null ? Number(bl) : 0;
        conf.basementCount = extractionData.basement_levels?.confidence || 'red';

        // Checkboxes
        prefill.hasKitchen = editedData.kitchen_present ?? extractionData.kitchen_present?.value ?? false;
        conf.hasKitchen = extractionData.kitchen_present?.confidence || 'red';

        prefill.sprinklerProposed = editedData.sprinklers_proposed ?? extractionData.sprinklers_proposed?.value ?? false;
        conf.sprinklerProposed = extractionData.sprinklers_proposed?.confidence || 'red';

        // Occupancy hint (for search)
        if (extractionData.primary_occupancy_hint?.proposed_code) {
            prefill.primaryOccupancy = extractionData.primary_occupancy_hint.proposed_code;
            conf.primaryOccupancy = extractionData.primary_occupancy_hint.confidence || 'red';
        }

        // Scale info
        prefill._detectedScale = extractionData.detected_scale;

        // Store in sessionStorage and navigate
        sessionStorage.setItem('firerulx_prefill', JSON.stringify(prefill));
        router.push('/manual?prefill=true');
    };

    /* ─── Helper: Editable field row in review popup ─── */
    const EditableField = ({ label, fieldKey, type = 'text', confidence, note }: {
        label: string;
        fieldKey: string;
        type?: 'text' | 'number' | 'checkbox';
        confidence: 'green' | 'amber' | 'red';
        note?: string;
    }) => {
        const colors = CONF_COLORS[confidence];
        const val = editedData[fieldKey];

        return (
            <div className="flex items-start gap-3 py-2.5 border-b border-slate-100" style={{ borderLeftWidth: 3, borderLeftColor: colors.border, paddingLeft: 12 }}>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: colors.dot }} />
                        <span className="text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{label}</span>
                        <span className="text-[10px] px-1.5 py-0.5 font-semibold uppercase tracking-wider" style={{ backgroundColor: colors.bg, color: colors.text }}>
                            {CONF_LABELS[confidence]}
                        </span>
                    </div>
                    {type === 'checkbox' ? (
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                            <input
                                type="checkbox"
                                checked={!!val}
                                onChange={(e) => setEditedData(prev => ({ ...prev, [fieldKey]: e.target.checked }))}
                                className="w-3.5 h-3.5 accent-[#0A192F]"
                            />
                            <span className="text-slate-700">{val ? 'Yes' : 'No'}</span>
                        </label>
                    ) : (
                        <input
                            type={type}
                            value={val as string ?? ''}
                            onChange={(e) => setEditedData(prev => ({ ...prev, [fieldKey]: type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value }))}
                            className="w-full px-2 py-1 border border-slate-300 text-sm font-mono focus:border-[#0A192F] outline-none"
                            placeholder={confidence === 'red' ? 'Not detected — enter manually' : ''}
                        />
                    )}
                    {note && <p className="text-[10px] text-slate-400 mt-0.5 leading-snug">{note}</p>}
                </div>
            </div>
        );
    };

    /* ─── ReadOnly field (for building_status, occupancy hint etc) ─── */
    const ReadOnlyField = ({ label, value, confidence, note }: {
        label: string;
        value: string | null;
        confidence: 'green' | 'amber' | 'red';
        note?: string;
    }) => {
        const colors = CONF_COLORS[confidence];
        return (
            <div className="flex items-start gap-3 py-2.5 border-b border-slate-100" style={{ borderLeftWidth: 3, borderLeftColor: colors.border, paddingLeft: 12 }}>
                <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: colors.dot }} />
                        <span className="text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{label}</span>
                        <span className="text-[10px] px-1.5 py-0.5 font-semibold uppercase tracking-wider" style={{ backgroundColor: colors.bg, color: colors.text }}>
                            {CONF_LABELS[confidence]}
                        </span>
                    </div>
                    <p className="text-sm text-slate-700 font-mono">
                        {value || <span className="text-slate-400 italic">Not detected — you&apos;ll need to enter this manually</span>}
                    </p>
                    {note && <p className="text-[10px] text-slate-400 mt-0.5">{note}</p>}
                </div>
            </div>
        );
    };

    return (
        <main className="min-h-screen bg-[#F8F9FA]">
            <Navbar />
            <div className="pt-24 pb-16 px-4 sm:px-6 lg:px-10">
                <div className="max-w-5xl mx-auto">
                    <header className="mb-8">
                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.25em]">FireRuleX · NBC Part 4</p>
                        <h1 className="text-3xl font-bold text-slate-900 tracking-tight mt-1">
                            New Analysis
                        </h1>
                        <p className="text-sm text-slate-500 mt-1">
                            Choose how you&apos;d like to enter your building data.
                        </p>
                    </header>

                    {/* ━━━ STEP: Choose Entry Mode ━━━ */}
                    {step === 'choose' && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {/* Option A: Manual Entry */}
                            <button
                                data-testid="entry-manual"
                                onClick={() => router.push('/manual')}
                                className="bg-white border border-slate-200 p-8 text-left hover:border-[#0A192F] hover:shadow-md transition-all group cursor-pointer"
                            >
                                <div className="text-3xl mb-4">✏️</div>
                                <h2 className="text-lg font-bold text-slate-900 group-hover:text-[#2962FF] transition-colors">
                                    Manual Entry
                                </h2>
                                <p className="text-sm text-slate-500 mt-2 leading-relaxed">
                                    Enter building parameters yourself — occupancy type, height, floors,
                                    areas, and construction details.
                                </p>
                                <p className="text-xs text-slate-400 mt-4 uppercase tracking-wider font-semibold">
                                    Best for → quick single-building checks
                                </p>
                            </button>

                            {/* Option B: Upload Building Plan */}
                            <button
                                data-testid="entry-upload"
                                onClick={() => setStep('upload')}
                                className="bg-white border border-slate-200 p-8 text-left hover:border-[#2962FF] hover:shadow-md transition-all group cursor-pointer"
                            >
                                <div className="text-3xl mb-4">📐</div>
                                <h2 className="text-lg font-bold text-slate-900 group-hover:text-[#2962FF] transition-colors">
                                    Upload Building Plan
                                </h2>
                                <p className="text-sm text-slate-500 mt-2 leading-relaxed">
                                    Upload a PDF or DWG floor plan. We&apos;ll extract building parameters
                                    automatically for you to review and confirm.
                                </p>
                                <p className="text-xs text-slate-400 mt-4 uppercase tracking-wider font-semibold">
                                    Best for → existing drawings with dimensions
                                </p>
                            </button>
                        </div>
                    )}

                    {/* ━━━ STEP: File Upload ━━━ */}
                    {step === 'upload' && (
                        <div className="max-w-xl mx-auto">
                            <div
                                className={`border-2 border-dashed p-12 text-center cursor-pointer transition-all ${dragOver ? 'border-[#2962FF] bg-blue-50' : 'border-slate-300 bg-white hover:border-slate-400'
                                    }`}
                                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                                onDragLeave={() => setDragOver(false)}
                                onDrop={handleDrop}
                                onClick={() => inputRef.current?.click()}
                            >
                                <input
                                    ref={inputRef}
                                    type="file"
                                    accept=".pdf,.dwg"
                                    onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }}
                                    className="hidden"
                                />
                                <div className="text-5xl opacity-60 mb-4">📐</div>
                                <p className="text-lg font-semibold text-slate-600">
                                    Drop your building plan here
                                </p>
                                <p className="text-sm text-slate-400 mt-1">
                                    or click to browse · PDF or DWG · Max 20MB
                                </p>
                            </div>

                            <button
                                onClick={() => setStep('choose')}
                                className="mt-4 text-xs text-slate-500 hover:text-slate-700 underline underline-offset-4"
                            >
                                ← Back to entry mode selection
                            </button>
                        </div>
                    )}

                    {/* ━━━ STEP: Processing ━━━ */}
                    {step === 'processing' && (
                        <div className="max-w-md mx-auto bg-white border border-slate-200 p-12 text-center">
                            <div className="w-12 h-12 border-3 border-slate-200 border-t-[#0A192F] rounded-full animate-spin mx-auto mb-6" />
                            <p className="text-lg font-semibold text-slate-700 mb-2">
                                {processingSteps[processingStep] || processingSteps[0]}
                            </p>
                            <p className="text-sm text-slate-400">
                                {file?.name} · {file ? `${(file.size / 1024 / 1024).toFixed(1)}MB` : ''}
                            </p>
                            <p className="text-xs text-slate-400 mt-4">
                                This may take a few seconds, especially for DWG conversion or scanned PDFs.
                            </p>
                        </div>
                    )}

                    {/* ━━━ STEP: Error ━━━ */}
                    {step === 'error' && (
                        <div className="max-w-md mx-auto bg-white border border-red-200 p-8 text-center">
                            <div className="text-4xl mb-4">⚠️</div>
                            <h2 className="text-lg font-bold text-slate-900 mb-2">Extraction Failed</h2>
                            <p className="text-sm text-red-600 mb-6">{error}</p>
                            <div className="flex flex-col gap-3">
                                <button
                                    onClick={() => { setFile(null); setError(''); setStep('upload'); }}
                                    className="w-full bg-[#0A192F] text-white py-3 text-xs uppercase tracking-widest font-bold hover:bg-slate-800"
                                >
                                    Try a Different File
                                </button>
                                <button
                                    onClick={() => router.push('/manual')}
                                    className="w-full border border-slate-300 text-slate-700 py-3 text-xs uppercase tracking-widest font-bold hover:border-[#0A192F]"
                                >
                                    Switch to Manual Entry
                                </button>
                            </div>
                        </div>
                    )}

                    {/* ━━━ STEP: Review Popup ━━━ */}
                    {step === 'review' && extractionData && (
                        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-8 pb-8 overflow-y-auto">
                            <div className="bg-white w-full max-w-2xl border border-slate-200 shadow-xl mx-4">
                                {/* Header */}
                                <div className="px-6 py-4 border-b border-slate-200 bg-slate-50">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h2 className="text-lg font-bold text-slate-900">Review Extracted Data</h2>
                                            <p className="text-xs text-slate-500 mt-0.5">
                                                {file?.name} · {extractionData.source_file_type?.replace('_', ' ')}
                                            </p>
                                        </div>
                                        {extractionData._extraction_quality && (
                                            <div className="text-right">
                                                <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Quality</p>
                                                <p className="text-sm font-mono text-[#2962FF]">
                                                    {extractionData._extraction_quality.quality_score}%
                                                </p>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Scale banner */}
                                {extractionData.detected_scale && (
                                    <div className="px-6 py-3 border-b border-slate-200" style={{
                                        backgroundColor: CONF_COLORS[extractionData.detected_scale.confidence].bg,
                                        borderLeftWidth: 4,
                                        borderLeftColor: CONF_COLORS[extractionData.detected_scale.confidence].border,
                                    }}>
                                        <p className="text-xs font-bold text-slate-600 uppercase tracking-wider mb-1">Detected Scale</p>
                                        <p className="text-sm font-mono font-bold" style={{ color: CONF_COLORS[extractionData.detected_scale.confidence].text }}>
                                            {extractionData.detected_scale.value || 'Not detected'}
                                            {extractionData.detected_scale.unit && ` (unit: ${extractionData.detected_scale.unit})`}
                                        </p>
                                        <p className="text-[10px] text-slate-500 mt-0.5">
                                            {extractionData.detected_scale.note || 'Scale affects every area-based field\'s trustworthiness.'}
                                        </p>
                                    </div>
                                )}

                                {/* Fields */}
                                <div className="px-6 py-4 max-h-[60vh] overflow-y-auto space-y-4">
                                    {/* Section: Project Info */}
                                    <div>
                                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.25em] mb-2">Section 01 · Project Info</p>
                                        <EditableField label="Project Name" fieldKey="project_name" confidence={extractionData.project_name?.confidence || 'red'} note={extractionData.project_name?.note} />
                                        <EditableField label="City" fieldKey="city" confidence={extractionData.city?.confidence || 'red'} note={extractionData.city?.note} />
                                        <EditableField label="State" fieldKey="state" confidence={extractionData.state?.confidence || 'red'} note={extractionData.state?.note} />
                                        <ReadOnlyField label="Building Status" value={null} confidence="red" note="Not derivable from a drawing — you'll select this in the form" />
                                    </div>

                                    {/* Section: Occupancy */}
                                    <div>
                                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.25em] mb-2">Section 02 · Occupancy</p>
                                        <ReadOnlyField
                                            label="Primary Occupancy (hint)"
                                            value={extractionData.primary_occupancy_hint?.proposed_code
                                                ? `${extractionData.primary_occupancy_hint.proposed_code} (from keyword: "${extractionData.primary_occupancy_hint.value}")`
                                                : null}
                                            confidence={extractionData.primary_occupancy_hint?.confidence || 'red'}
                                            note={extractionData.primary_occupancy_hint?.note}
                                        />
                                    </div>

                                    {/* Section: Building Parameters */}
                                    <div>
                                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.25em] mb-2">Section 03 · Building Parameters</p>
                                        <EditableField label="Height (m)" fieldKey="height_m" type="number" confidence={extractionData.height_m?.confidence || 'red'} note={extractionData.height_m?.note} />
                                        <EditableField label="Number of Floors" fieldKey="floors_count" type="number" confidence={extractionData.floors_count?.confidence || 'red'} note={extractionData.floors_count?.note} />
                                        <ReadOnlyField
                                            label="Construction Type"
                                            value={extractionData.construction_type?.value
                                                ? (extractionData.construction_type.value === 'type12' ? 'Type 1 / 2 — fire-resistive' : 'Type 3 / 4 — ordinary/wood-frame')
                                                : null}
                                            confidence={extractionData.construction_type?.confidence || 'red'}
                                            note={extractionData.construction_type?.note}
                                        />

                                        {/* Per-floor areas */}
                                        {extractionData.per_floor_areas_m2?.length > 0 && (
                                            <div className="py-2.5 border-b border-slate-100" style={{ borderLeftWidth: 3, borderLeftColor: '#FFB300', paddingLeft: 12 }}>
                                                <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.15em] mb-2">Per-Floor Areas (m²)</p>
                                                <div className="grid grid-cols-2 gap-1.5">
                                                    {extractionData.per_floor_areas_m2.map((fa, i) => (
                                                        <div key={i} className="flex items-center gap-2 text-xs">
                                                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CONF_COLORS[fa.confidence].dot }} />
                                                            <span className="font-mono text-slate-500 w-8">{fa.floor_label}</span>
                                                            <span className="font-mono text-slate-700">{fa.value?.toLocaleString() ?? '—'} m²</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        <EditableField label="Basement Area (m²)" fieldKey="basement_area_m2" type="number" confidence={extractionData.basement_area_m2?.confidence || 'red'} note={extractionData.basement_area_m2?.note} />
                                        <EditableField label="Basement Levels" fieldKey="basement_levels" type="number" confidence={extractionData.basement_levels?.confidence || 'red'} note={extractionData.basement_levels?.note} />
                                        <EditableField label="Kitchen Present" fieldKey="kitchen_present" type="checkbox" confidence={extractionData.kitchen_present?.confidence || 'red'} note={extractionData.kitchen_present?.note} />
                                        <EditableField label="Sprinklers Proposed" fieldKey="sprinklers_proposed" type="checkbox" confidence={extractionData.sprinklers_proposed?.confidence || 'red'} note={extractionData.sprinklers_proposed?.note} />
                                    </div>

                                    {/* Warnings */}
                                    {extractionData.warnings && extractionData.warnings.length > 0 && (
                                        <div className="mt-4 px-3 py-2 bg-amber-50 border border-amber-200 text-xs text-amber-700 space-y-1">
                                            <p className="font-bold uppercase tracking-wider text-[10px]">Extraction Notes</p>
                                            {extractionData.warnings.map((w, i) => (
                                                <p key={i}>• {w}</p>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                {/* Actions */}
                                <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex flex-col sm:flex-row gap-3">
                                    <button
                                        data-testid="review-back"
                                        onClick={() => { setFile(null); setExtractionData(null); setStep('upload'); }}
                                        className="flex-1 border border-slate-300 text-slate-700 py-3 text-xs uppercase tracking-widest font-bold hover:border-[#0A192F] transition-colors"
                                    >
                                        ← Back / Try a Different File
                                    </button>
                                    <button
                                        data-testid="review-confirm"
                                        onClick={confirmAndContinue}
                                        className="flex-1 bg-[#0A192F] text-white py-3 text-xs uppercase tracking-widest font-bold hover:bg-slate-800 transition-colors"
                                    >
                                        Confirm & Continue →
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
            <Footer />
        </main>
    );
}
