'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import type { OccupancyGroupInfo, OccupancyZone } from '@/types';

/* ─── Confidence indicator colors (matches review popup) ─── */
const CONF_BORDER: Record<string, string> = {
    green: '#4CAF50',
    amber: '#FFB300',
    red: '#E53935',
};

function ManualPageInner() {
    // Wrap in Suspense-compatible inner component
    return <ManualForm />;
}

export default function ManualPage() {
    return (
        <Suspense fallback={<div className="min-h-screen bg-[#F8F9FA] flex items-center justify-center text-slate-500">Loading…</div>}>
            <ManualPageInner />
        </Suspense>
    );
}

const API_URL = '';

interface Preset {
    id: string;
    label: string;
    primary: string;
    secondary: string[];
}

function ManualForm() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const isPrefill = searchParams.get('prefill') === 'true';

    // Occupancy catalogue
    const [groups, setGroups] = useState<OccupancyGroupInfo[]>([]);
    const [presets, setPresets] = useState<Preset[]>([]);
    const [loading, setLoading] = useState(true);

    // Confidence indicators for pre-filled fields
    const [fieldConfidence, setFieldConfidence] = useState<Record<string, string>>({});

    // Form state
    const [projectName, setProjectName] = useState('');
    const [city, setCity] = useState('');
    const [state, setState] = useState('');
    const [buildingStatus, setBuildingStatus] = useState<'proposed' | 'existing' | 'under_construction'>('proposed');

    const [mode, setMode] = useState<'single' | 'mixed'>('single');
    const [primaryOccupancy, setPrimaryOccupancy] = useState<string>('');
    const [secondaryOccupancies, setSecondaryOccupancies] = useState<string[]>([]);
    const [zones, setZones] = useState<OccupancyZone[]>([]);

    const [buildingHeight, setBuildingHeight] = useState<number>(0);
    const [numberOfFloors, setNumberOfFloors] = useState<number>(1);
    const [floorAreas, setFloorAreas] = useState<number[]>([0]);
    const [basementArea, setBasementArea] = useState<number>(0);
    const [basementCount, setBasementCount] = useState<number>(0);
    const [constructionType, setConstructionType] = useState<'type12' | 'type34'>('type12');
    const [hasKitchen, setHasKitchen] = useState(false);
    const [sprinklerProposed, setSprinklerProposed] = useState(false);

    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [occSearch, setOccSearch] = useState('');

    // ── Load pre-fill data from extraction pipeline ──
    useEffect(() => {
        if (!isPrefill) return;
        const stored = sessionStorage.getItem('firerulx_prefill');
        if (!stored) return;
        try {
            const data = JSON.parse(stored);
            if (data._source !== 'extraction') return;

            // Pre-fill form fields
            if (data.projectName) setProjectName(data.projectName);
            if (data.city) setCity(data.city);
            if (data.state) setState(data.state);
            if (data.buildingHeight) setBuildingHeight(Number(data.buildingHeight));
            if (data.numberOfFloors) {
                const n = Number(data.numberOfFloors);
                setNumberOfFloors(n);
                if (data.floorAreas && Array.isArray(data.floorAreas)) {
                    setFloorAreas(data.floorAreas.map((a: number) => a || 0));
                } else {
                    setFloorAreas(Array(n).fill(0));
                }
            }
            if (data.constructionType === 'type12' || data.constructionType === 'type34') {
                setConstructionType(data.constructionType);
            }
            if (data.basementArea) setBasementArea(Number(data.basementArea));
            if (data.basementCount) setBasementCount(Number(data.basementCount));
            if (data.hasKitchen) setHasKitchen(!!data.hasKitchen);
            if (data.sprinklerProposed) setSprinklerProposed(!!data.sprinklerProposed);
            if (data.primaryOccupancy) setPrimaryOccupancy(data.primaryOccupancy);

            // Store confidence levels
            if (data._confidence) {
                setFieldConfidence(data._confidence);
            }

            // Clean up — don't re-apply on navigation back
            sessionStorage.removeItem('firerulx_prefill');
        } catch {
            // Ignore parse errors
        }
    }, [isPrefill]);

    useEffect(() => {
        const timer = setTimeout(() => setLoading(false), 8000);

        const parseJsonResponse = async (response: Response, label: string) => {
            const contentType = response.headers.get('content-type') || '';
            if (!response.ok) {
                const text = await response.text();
                throw new Error(`${label} request failed (${response.status}): ${text.slice(0, 200)}`);
            }
            if (contentType.includes('application/json')) {
                return response.json();
            }
            const text = await response.text();
            throw new Error(`${label} returned non-JSON content: ${text.slice(0, 200)}`);
        };

        Promise.all([
            fetch(`${API_URL}/api/occupancies`).then((r) => parseJsonResponse(r, 'Occupancy catalogue')),
            fetch(`${API_URL}/api/occupancy-presets`).then((r) => parseJsonResponse(r, 'Occupancy presets')),
        ])
            .then(([occ, pres]) => {
                clearTimeout(timer);
                setGroups(occ.groups || []);
                setPresets(pres.presets || []);
                setLoading(false);
            })
            .catch((e) => {
                clearTimeout(timer);
                setLoading(false);
                setError(`Could not load occupancy catalogue: ${e instanceof Error ? e.message : String(e)}`);
            });
        return () => clearTimeout(timer);
    }, []);

    // Flatten subdivisions for multi-select
    const allSubdivisions = useMemo(
        () =>
            groups.flatMap((g) =>
                g.subdivisions.map((s) => ({
                    code: s.code,
                    label: s.label,
                    group: g.group,
                    groupLabel: g.label,
                    examples: s.examples || [],
                })),
            ),
        [groups],
    );

    const filteredSubs = useMemo(() => {
        const q = occSearch.trim().toLowerCase();
        if (!q) return allSubdivisions;
        return allSubdivisions.filter(
            (s) =>
                s.code.toLowerCase().includes(q) ||
                s.label.toLowerCase().includes(q) ||
                s.groupLabel.toLowerCase().includes(q) ||
                s.examples.some((e) => e.toLowerCase().includes(q)),
        );
    }, [occSearch, allSubdivisions]);

    const setFloors = (n: number) => {
        const count = Math.max(1, Math.min(200, n));
        setNumberOfFloors(count);
        setFloorAreas((prev) => {
            const arr = [...prev];
            const last = arr[arr.length - 1] || 0;
            while (arr.length < count) arr.push(last);
            arr.length = count;
            return arr;
        });
    };

    const applyPreset = (p: Preset) => {
        setMode('mixed');
        setPrimaryOccupancy(p.primary);
        setSecondaryOccupancies(p.secondary);
        setZones([]);
    };

    const toggleSecondary = (code: string) => {
        setSecondaryOccupancies((prev) =>
            prev.includes(code) ? prev.filter((x) => x !== code) : [...prev, code],
        );
    };

    const addZone = () => {
        setZones((prev) => [
            ...prev,
            { occupancyCode: primaryOccupancy || (allSubdivisions[0]?.code ?? ''), label: '', floorRange: '', areaM2: 0 },
        ]);
    };

    const updateZone = (idx: number, patch: Partial<OccupancyZone>) => {
        setZones((prev) => prev.map((z, i) => (i === idx ? { ...z, ...patch } : z)));
    };

    const removeZone = (idx: number) => {
        setZones((prev) => prev.filter((_, i) => i !== idx));
    };

    const totalArea = floorAreas.reduce((s, a) => s + (a || 0), 0);
    const canSubmit =
        !!primaryOccupancy && buildingHeight > 0 && numberOfFloors > 0 && floorAreas.every((a) => a > 0);

    const submit = async () => {
        setError(null);
        if (!canSubmit) {
            setError('Fill in occupancy, height, floors and per-floor areas.');
            return;
        }
        setSubmitting(true);
        try {
            const body = {
                projectName,
                city,
                state,
                buildingStatus,
                buildingHeight,
                numberOfFloors,
                floorAreas,
                basementArea,
                basementCount,
                constructionType,
                hasKitchen,
                sprinklerProposed,
                occupancySelection: {
                    mode,
                    primaryOccupancy,
                    secondaryOccupancies: mode === 'mixed' ? secondaryOccupancies : [],
                    occupancyZones: zones.filter((z) => z.occupancyCode),
                },
            };
            const res = await fetch(`${API_URL}/api/analyze-mixed`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || 'Analysis failed');
            sessionStorage.setItem('firerulx_result', JSON.stringify(data));
            router.push('/results');
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Something went wrong');
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <main className="min-h-screen bg-[#F8F9FA]">
            <Navbar />
            <div className="pt-24 pb-16 px-4 sm:px-6 lg:px-10">
                <div className="max-w-5xl mx-auto">
                    <header className="mb-8 flex flex-col md:flex-row md:items-end md:justify-between gap-3">
                        <div>
                            <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.25em]">FireRuleX · NBC Part 4</p>
                            <h1 className="text-3xl font-bold text-slate-900 tracking-tight mt-1">
                                Building Compliance — New Analysis
                            </h1>
                            <p className="text-sm text-slate-500 mt-1">
                                Select occupancy (single or mixed) and enter building parameters. Strictest NBC Part 4 rule wins per parameter.
                            </p>
                        </div>
                        <button
                            data-testid="back-home-btn"
                            onClick={() => router.push('/')}
                            className="text-xs font-semibold text-slate-600 hover:text-slate-900 underline underline-offset-4"
                        >
                            ← Back to home
                        </button>
                    </header>

                    {loading ? (
                        <div className="text-slate-500">Loading occupancy catalogue…</div>
                    ) : (
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                            {/* Left column — Occupancy */}
                            <section className="lg:col-span-2 space-y-6">
                                {/* Project context */}
                                <div className="bg-white border border-slate-200">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Section 01 · Project</p>
                                    </div>
                                    <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <Field label="Project Name" testid="input-project-name" confidence={fieldConfidence.projectName}>
                                            <input
                                                data-testid="input-project-name"
                                                value={projectName}
                                                onChange={(e) => setProjectName(e.target.value)}
                                                placeholder="e.g. Skyline Towers"
                                                className="w-full px-3 py-2 border border-slate-300 rounded-none focus:border-[#0A192F] outline-none text-sm"
                                            />
                                        </Field>
                                        <Field label="City" confidence={fieldConfidence.city}>
                                            <input
                                                data-testid="input-city"
                                                value={city}
                                                onChange={(e) => setCity(e.target.value)}
                                                placeholder="e.g. Mumbai"
                                                className="w-full px-3 py-2 border border-slate-300 rounded-none focus:border-[#0A192F] outline-none text-sm"
                                            />
                                        </Field>
                                        <Field label="State" confidence={fieldConfidence.state}>
                                            <input
                                                data-testid="input-state"
                                                value={state}
                                                onChange={(e) => setState(e.target.value)}
                                                placeholder="e.g. Maharashtra"
                                                className="w-full px-3 py-2 border border-slate-300 rounded-none focus:border-[#0A192F] outline-none text-sm"
                                            />
                                        </Field>
                                        <Field label="Building Status" confidence={fieldConfidence.buildingStatus}>
                                            <select
                                                data-testid="select-status"
                                                value={buildingStatus}
                                                onChange={(e) => setBuildingStatus(e.target.value as 'proposed' | 'existing' | 'under_construction')}
                                                className="w-full px-3 py-2 border border-slate-300 rounded-none focus:border-[#0A192F] outline-none text-sm bg-white"
                                            >
                                                <option value="proposed">Proposed</option>
                                                <option value="existing">Existing</option>
                                                <option value="under_construction">Under construction</option>
                                            </select>
                                        </Field>
                                    </div>
                                </div>

                                {/* Occupancy selection */}
                                <div className="bg-white border border-slate-200">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Section 02 · Occupancy</p>
                                        <div className="flex bg-white border border-slate-300 divide-x divide-slate-300">
                                            <button
                                                data-testid="mode-single-btn"
                                                onClick={() => setMode('single')}
                                                className={`text-xs px-3 py-1.5 font-semibold uppercase tracking-wide ${mode === 'single' ? 'bg-[#0A192F] text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                                            >
                                                Single
                                            </button>
                                            <button
                                                data-testid="mode-mixed-btn"
                                                onClick={() => setMode('mixed')}
                                                className={`text-xs px-3 py-1.5 font-semibold uppercase tracking-wide ${mode === 'mixed' ? 'bg-[#0A192F] text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                                            >
                                                Mixed
                                            </button>
                                        </div>
                                    </div>

                                    <div className="p-5 space-y-4">
                                        {mode === 'mixed' && presets.length > 0 && (
                                            <div>
                                                <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em] mb-2">Common combinations</p>
                                                <div className="flex flex-wrap gap-2">
                                                    {presets.map((p) => (
                                                        <button
                                                            key={p.id}
                                                            data-testid={`preset-${p.id}`}
                                                            onClick={() => applyPreset(p)}
                                                            className="text-xs px-3 py-1.5 border border-slate-300 text-slate-700 hover:border-[#2962FF] hover:text-[#2962FF] transition-colors"
                                                        >
                                                            {p.label}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        <Field label="Primary occupancy" confidence={fieldConfidence.primaryOccupancy}>
                                            <input
                                                type="text"
                                                data-testid="input-occ-search"
                                                placeholder="Search: e.g. hotel, banquet, mall, hospital…"
                                                value={occSearch}
                                                onChange={(e) => setOccSearch(e.target.value)}
                                                className="w-full mb-2 px-3 py-2 border border-slate-300 rounded-none focus:border-[#0A192F] outline-none text-sm font-mono"
                                            />
                                            <select
                                                data-testid="select-primary-occupancy"
                                                value={primaryOccupancy}
                                                onChange={(e) => setPrimaryOccupancy(e.target.value)}
                                                className="w-full px-3 py-2 border border-slate-300 rounded-none focus:border-[#0A192F] outline-none text-sm bg-white font-mono"
                                            >
                                                <option value="">— select occupancy —</option>
                                                {groups.map((g) => (
                                                    <optgroup key={g.group} label={`${g.group} · ${g.label}`}>
                                                        {g.subdivisions
                                                            .filter((s) => filteredSubs.some((fs) => fs.code === s.code))
                                                            .map((s) => (
                                                                <option key={s.code} value={s.code}>
                                                                    {s.code} — {s.label}
                                                                </option>
                                                            ))}
                                                    </optgroup>
                                                ))}
                                            </select>
                                        </Field>

                                        {mode === 'mixed' && (
                                            <div>
                                                <label className="block text-xs font-bold text-slate-500 uppercase tracking-[0.2em] mb-2">
                                                    Secondary occupancies
                                                </label>
                                                <div className="border border-slate-200 max-h-56 overflow-y-auto divide-y divide-slate-100">
                                                    {filteredSubs.map((s) => {
                                                        const isPrimary = s.code === primaryOccupancy;
                                                        const checked = secondaryOccupancies.includes(s.code);
                                                        return (
                                                            <label
                                                                key={s.code}
                                                                className={`flex items-center gap-3 px-3 py-1.5 text-xs cursor-pointer transition-colors ${isPrimary ? 'bg-slate-100 text-slate-400 cursor-not-allowed' : 'hover:bg-slate-50'}`}
                                                            >
                                                                <input
                                                                    type="checkbox"
                                                                    data-testid={`secondary-${s.code}`}
                                                                    checked={checked}
                                                                    disabled={isPrimary}
                                                                    onChange={() => toggleSecondary(s.code)}
                                                                    className="w-3.5 h-3.5 accent-[#0A192F]"
                                                                />
                                                                <span className="font-mono text-[#2962FF] w-14 shrink-0">{s.code}</span>
                                                                <span className="text-slate-800">{s.label}</span>
                                                                <span className="text-slate-400 ml-auto text-[10px]">{s.groupLabel}</span>
                                                            </label>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        )}

                                        {mode === 'mixed' && (
                                            <div>
                                                <div className="flex items-center justify-between mb-2">
                                                    <label className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">
                                                        Per-zone allocation <span className="text-slate-400 normal-case font-normal">(optional)</span>
                                                    </label>
                                                    <button
                                                        data-testid="add-zone-btn"
                                                        onClick={addZone}
                                                        className="text-xs px-3 py-1 bg-[#0A192F] text-white hover:bg-slate-800"
                                                    >
                                                        + Add zone
                                                    </button>
                                                </div>
                                                {zones.length === 0 ? (
                                                    <p className="text-xs text-slate-400 border border-dashed border-slate-300 px-3 py-3">
                                                        Zones let you attach floor range and area to each occupancy. If left empty, the whole building
                                                        is evaluated for every selected occupancy.
                                                    </p>
                                                ) : (
                                                    <div className="space-y-2">
                                                        {zones.map((z, i) => (
                                                            <div key={i} data-testid={`zone-row-${i}`} className="grid grid-cols-12 gap-2 items-end border border-slate-200 p-2">
                                                                <div className="col-span-3">
                                                                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Occupancy</label>
                                                                    <select
                                                                        value={z.occupancyCode}
                                                                        onChange={(e) => updateZone(i, { occupancyCode: e.target.value })}
                                                                        className="w-full px-2 py-1 border border-slate-300 text-xs bg-white font-mono"
                                                                    >
                                                                        {allSubdivisions.map((s) => (
                                                                            <option key={s.code} value={s.code}>{s.code}</option>
                                                                        ))}
                                                                    </select>
                                                                </div>
                                                                <div className="col-span-4">
                                                                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Label</label>
                                                                    <input
                                                                        value={z.label || ''}
                                                                        onChange={(e) => updateZone(i, { label: e.target.value })}
                                                                        placeholder="e.g. Hotel"
                                                                        className="w-full px-2 py-1 border border-slate-300 text-xs"
                                                                    />
                                                                </div>
                                                                <div className="col-span-2">
                                                                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Floor range</label>
                                                                    <input
                                                                        value={z.floorRange || ''}
                                                                        onChange={(e) => updateZone(i, { floorRange: e.target.value })}
                                                                        placeholder="1-3"
                                                                        className="w-full px-2 py-1 border border-slate-300 text-xs font-mono"
                                                                    />
                                                                </div>
                                                                <div className="col-span-2">
                                                                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-0.5">Area m²</label>
                                                                    <input
                                                                        type="number"
                                                                        value={z.areaM2 || ''}
                                                                        onChange={(e) => updateZone(i, { areaM2: Number(e.target.value) })}
                                                                        className="w-full px-2 py-1 border border-slate-300 text-xs font-mono text-right"
                                                                    />
                                                                </div>
                                                                <button
                                                                    data-testid={`remove-zone-${i}`}
                                                                    onClick={() => removeZone(i)}
                                                                    className="col-span-1 text-xs text-red-600 hover:bg-red-50 py-1 border border-red-200"
                                                                >
                                                                    ×
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Building parameters */}
                                <div className="bg-white border border-slate-200">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Section 03 · Building parameters</p>
                                    </div>
                                    <div className="p-5 space-y-4">
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                            <Field label="Height (m)" confidence={fieldConfidence.buildingHeight}>
                                                <input
                                                    type="number"
                                                    data-testid="input-height"
                                                    value={buildingHeight || ''}
                                                    onChange={(e) => setBuildingHeight(Number(e.target.value))}
                                                    className="w-full px-3 py-2 border border-slate-300 focus:border-[#0A192F] outline-none text-sm font-mono text-right"
                                                    step={0.5}
                                                    min={0}
                                                />
                                            </Field>
                                            <Field label="Number of Floors" confidence={fieldConfidence.numberOfFloors}>
                                                <input
                                                    type="number"
                                                    data-testid="input-floors"
                                                    value={numberOfFloors || ''}
                                                    onChange={(e) => setFloors(Number(e.target.value))}
                                                    className="w-full px-3 py-2 border border-slate-300 focus:border-[#0A192F] outline-none text-sm font-mono text-right"
                                                    min={1}
                                                />
                                            </Field>
                                            <Field label="Construction Type" confidence={fieldConfidence.constructionType}>
                                                <select
                                                    data-testid="select-construction"
                                                    value={constructionType}
                                                    onChange={(e) => setConstructionType(e.target.value as 'type12' | 'type34')}
                                                    className="w-full px-3 py-2 border border-slate-300 focus:border-[#0A192F] outline-none text-sm bg-white"
                                                >
                                                    <option value="type12">Type 1 / 2 — fire-resistive</option>
                                                    <option value="type34">Type 3 / 4 — ordinary/wood-frame</option>
                                                </select>
                                            </Field>
                                        </div>

                                        <div>
                                            <label className="block text-xs font-bold text-slate-500 uppercase tracking-[0.2em] mb-2">Per-floor areas (m²)</label>
                                            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-56 overflow-y-auto pr-1">
                                                {floorAreas.map((a, idx) => (
                                                    <div key={idx} className="flex items-center gap-2">
                                                        <span className="text-[10px] text-slate-500 uppercase tracking-wider w-14 shrink-0 font-mono">
                                                            {idx === 0 ? 'GF' : `F${idx}`}
                                                        </span>
                                                        <input
                                                            type="number"
                                                            data-testid={`input-floor-area-${idx}`}
                                                            value={a || ''}
                                                            onChange={(e) => {
                                                                const arr = [...floorAreas];
                                                                arr[idx] = Number(e.target.value);
                                                                setFloorAreas(arr);
                                                            }}
                                                            className="flex-1 px-2 py-1 border border-slate-300 text-xs font-mono text-right focus:border-[#0A192F] outline-none"
                                                        />
                                                    </div>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-slate-100">
                                            <Field label="Basement Area (m²)" confidence={fieldConfidence.basementArea}>
                                                <input
                                                    type="number"
                                                    data-testid="input-basement-area"
                                                    value={basementArea || ''}
                                                    onChange={(e) => setBasementArea(Number(e.target.value))}
                                                    className="w-full px-3 py-2 border border-slate-300 focus:border-[#0A192F] outline-none text-sm font-mono text-right"
                                                    min={0}
                                                />
                                            </Field>
                                            <Field label="Basement Levels" confidence={fieldConfidence.basementCount}>
                                                <input
                                                    type="number"
                                                    data-testid="input-basement-count"
                                                    value={basementCount || ''}
                                                    onChange={(e) => setBasementCount(Number(e.target.value))}
                                                    className="w-full px-3 py-2 border border-slate-300 focus:border-[#0A192F] outline-none text-sm font-mono text-right"
                                                    min={0}
                                                />
                                            </Field>
                                            <div className="flex items-center gap-3 pt-6">
                                                <Field label="Kitchen present" confidence={fieldConfidence.hasKitchen}>
                                                    <label className="flex items-center gap-2 text-xs cursor-pointer mt-1">
                                                        <input
                                                            type="checkbox"
                                                            data-testid="input-has-kitchen"
                                                            checked={hasKitchen}
                                                            onChange={(e) => setHasKitchen(e.target.checked)}
                                                            className="w-3.5 h-3.5 accent-[#0A192F]"
                                                        />
                                                        Yes
                                                    </label>
                                                </Field>
                                                <Field label="Sprinklers proposed" confidence={fieldConfidence.sprinklerProposed}>
                                                    <label className="flex items-center gap-2 text-xs cursor-pointer mt-1">
                                                        <input
                                                            type="checkbox"
                                                            data-testid="input-sprinkler"
                                                            checked={sprinklerProposed}
                                                            onChange={(e) => setSprinklerProposed(e.target.checked)}
                                                            className="w-3.5 h-3.5 accent-[#0A192F]"
                                                        />
                                                        Yes
                                                    </label>
                                                </Field>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </section>

                            {/* Right column — Summary + submit */}
                            <aside className="lg:col-span-1">
                                <div className="bg-white border border-slate-200 sticky top-24">
                                    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
                                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">Live summary</p>
                                    </div>
                                    <div className="p-5 space-y-4 text-sm">
                                        <SummaryRow k="Mode" v={mode.toUpperCase()} />
                                        <SummaryRow k="Primary" v={primaryOccupancy || '—'} mono />
                                        {mode === 'mixed' && (
                                            <SummaryRow k="Secondaries" v={secondaryOccupancies.length ? secondaryOccupancies.join(', ') : '—'} mono />
                                        )}
                                        <SummaryRow k="Height" v={buildingHeight ? `${buildingHeight} m` : '—'} />
                                        <SummaryRow k="Floors" v={String(numberOfFloors)} />
                                        <SummaryRow k="Total area" v={`${totalArea.toLocaleString()} m²`} />
                                        {basementArea > 0 && <SummaryRow k="Basement" v={`${basementArea.toLocaleString()} m² · ${basementCount} lvl`} />}

                                        {mode === 'mixed' && zones.length > 0 && (
                                            <div>
                                                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] mb-1">Zones</p>
                                                <ul className="text-xs space-y-1 font-mono">
                                                    {zones.map((z, i) => (
                                                        <li key={i} className="flex justify-between gap-2 border-b border-slate-100 pb-1">
                                                            <span className="text-[#2962FF]">{z.occupancyCode}</span>
                                                            <span className="text-slate-500">{z.floorRange || '—'}</span>
                                                            <span className="text-slate-700">{z.areaM2 || '—'}m²</span>
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        {error && (
                                            <p className="text-xs text-red-600 border-l-2 border-red-500 pl-2 mt-2">{error}</p>
                                        )}

                                        <button
                                            data-testid="analyze-btn"
                                            onClick={submit}
                                            disabled={!canSubmit || submitting}
                                            className="w-full bg-[#0A192F] text-white py-3 text-sm font-bold uppercase tracking-widest hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                        >
                                            {submitting ? 'Analyzing…' : 'Run Compliance Analysis'}
                                        </button>
                                    </div>
                                </div>
                            </aside>
                        </div>
                    )}
                </div>
            </div>
            <Footer />
        </main>
    );
}

function Field({ label, children, testid, confidence }: { label: string; children: React.ReactNode; testid?: string; confidence?: string }) {
    const borderColor = confidence ? CONF_BORDER[confidence] : undefined;
    return (
        <div data-testid={testid} style={borderColor ? { borderLeft: `3px solid ${borderColor}`, paddingLeft: 8 } : undefined}>
            <div className="flex items-center gap-2 mb-1.5">
                <label className="block text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{label}</label>
                {confidence && confidence !== 'red' && (
                    <span className="text-[9px] px-1 py-0.5 font-bold uppercase tracking-wider" style={{
                        backgroundColor: confidence === 'green' ? '#E8F5E9' : '#FFF8E1',
                        color: confidence === 'green' ? '#2E7D32' : '#F57F17',
                    }}>detected</span>
                )}
            </div>
            {children}
        </div>
    );
}

function SummaryRow({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
    return (
        <div className="flex items-center justify-between border-b border-slate-100 pb-1.5 gap-3">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">{k}</span>
            <span className={`text-xs text-slate-800 text-right ${mono ? 'font-mono text-[#2962FF]' : ''}`}>{v}</span>
        </div>
    );
}
