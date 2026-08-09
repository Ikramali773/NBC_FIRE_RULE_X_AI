'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import type { BuildingInput, AnalyzeResponse } from '@/types';

const defaultInput: BuildingInput = {
    buildingName: '',
    buildingType: '',
    totalFloorArea: 0,
    numberOfFloors: 1,
    floorAreas: [0],
    buildingHeight: 0,
    occupantCount: 0,
    hasKitchen: false,
    hasFlammableLiquids: false,
    hasFlammableGases: false,
    hasCombustibleMetals: false,
    hasElectricalHazards: false,
};

function ConfirmForm() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const isManual = searchParams.get('manual') === 'true';

    const [form, setForm] = useState<BuildingInput>(defaultInput);
    const [confidenceFlags, setConfidenceFlags] = useState<string[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Load AI-extracted data if coming from analysis
    useEffect(() => {
        if (isManual) return;
        const stored = sessionStorage.getItem('firerulx_result');
        if (stored) {
            try {
                const data: AnalyzeResponse = JSON.parse(stored);
                setForm(data.extraction);
                setConfidenceFlags(data.confidence.flags);
            } catch {
                // Ignore parse errors, use defaults
            }
        }
    }, [isManual]);

    const updateField = (field: keyof BuildingInput, value: string | number | boolean) => {
        setForm((prev) => ({ ...prev, [field]: value }));
    };

    const updateFloorArea = (index: number, value: number) => {
        setForm((prev) => {
            const newAreas = [...prev.floorAreas];
            newAreas[index] = value;
            return { ...prev, floorAreas: newAreas };
        });
    };

    const handleFloorCountChange = (count: number) => {
        const safeCount = Math.max(1, Math.min(50, count));
        setForm((prev) => {
            const newAreas = Array(safeCount)
                .fill(0)
                .map((_, i) => prev.floorAreas[i] || 0);
            return { ...prev, numberOfFloors: safeCount, floorAreas: newAreas };
        });
    };

    const handleSubmit = async () => {
        setLoading(true);
        setError(null);

        try {
            let API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
            if (API_BASE_URL && !API_BASE_URL.startsWith('http')) {
                API_BASE_URL = `https://${API_BASE_URL}`;
            }
            const response = await fetch(`${API_BASE_URL}/api/analyze-manual`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(form),
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Analysis failed');
            }

            const data = await response.json();
            sessionStorage.setItem('firerulx_result', JSON.stringify(data));
            router.push('/results');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Something went wrong');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="pt-24 pb-8 px-4 sm:px-6 lg:px-8">
            <div className="max-w-2xl mx-auto">
                <h1 className="text-2xl font-bold text-slate-900 mb-2">
                    {isManual ? '✏️ Enter Building Data' : '🔍 Review AI Extraction'}
                </h1>

                {!isManual && confidenceFlags.length > 0 && (
                    <div className="mb-6 px-4 py-3 rounded-lg bg-amber-50 border border-amber-200">
                        <p className="text-sm font-semibold text-amber-700 mb-2">
                            ⚠️ AI extraction confidence is low. Please review and correct:
                        </p>
                        <ul className="text-sm text-amber-600 space-y-1">
                            {confidenceFlags.map((flag, i) => (
                                <li key={i}>• {flag}</li>
                            ))}
                        </ul>
                    </div>
                )}

                <div className="card space-y-6">
                    {/* Building Name */}
                    <div>
                        <label className="block text-sm font-medium text-slate-700 mb-1">
                            Building Name
                        </label>
                        <input
                            type="text"
                            value={form.buildingName}
                            onChange={(e) => updateField('buildingName', e.target.value)}
                            placeholder="e.g. Acme Office Complex"
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition text-sm"
                        />
                    </div>

                    {/* Building Type */}
                    <div>
                        <label className="block text-sm font-medium text-slate-700 mb-1">
                            Building Functional Type
                        </label>
                        <input
                            type="text"
                            value={form.buildingType}
                            onChange={(e) => updateField('buildingType', e.target.value)}
                            placeholder="e.g. Office, Hospital, School, Residential"
                            className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition text-sm"
                        />
                    </div>

                    {/* Area + Floors row */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-slate-700 mb-1">
                                Total Floor Area (m²) *
                            </label>
                            <input
                                type="number"
                                value={form.totalFloorArea || ''}
                                onChange={(e) => updateField('totalFloorArea', Number(e.target.value))}
                                min={0}
                                className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition text-sm"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-slate-700 mb-1">
                                Number of Floors *
                            </label>
                            <input
                                type="number"
                                value={form.numberOfFloors || ''}
                                onChange={(e) => handleFloorCountChange(Number(e.target.value))}
                                min={1}
                                max={50}
                                className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition text-sm"
                            />
                        </div>
                    </div>

                    {/* Floor areas */}
                    <div>
                        <label className="block text-sm font-medium text-slate-700 mb-2">
                            Area per Floor (m²) *
                        </label>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                            {form.floorAreas.map((area, i) => (
                                <div key={i} className="flex items-center gap-2">
                                    <span className="text-xs text-slate-400 w-8">F{i + 1}</span>
                                    <input
                                        type="number"
                                        value={area || ''}
                                        onChange={(e) => updateFloorArea(i, Number(e.target.value))}
                                        min={0}
                                        className="w-full px-2 py-1.5 rounded-lg border border-slate-200 focus:border-orange-400 outline-none transition text-sm"
                                    />
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Height + Occupants */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-slate-700 mb-1">
                                Building Height (m)
                            </label>
                            <input
                                type="number"
                                value={form.buildingHeight || ''}
                                onChange={(e) => updateField('buildingHeight', Number(e.target.value))}
                                min={0}
                                className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition text-sm"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-slate-700 mb-1">
                                Max Occupants
                            </label>
                            <input
                                type="number"
                                value={form.occupantCount || ''}
                                onChange={(e) => updateField('occupantCount', Number(e.target.value))}
                                min={0}
                                className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition text-sm"
                            />
                        </div>
                    </div>

                    {/* Hazard toggles */}
                    <div>
                        <label className="block text-sm font-medium text-slate-700 mb-3">
                            Hazard Flags
                        </label>
                        <div className="space-y-3">
                            {[
                                { key: 'hasKitchen' as const, label: '🍳 Kitchen / Cooking Area' },
                                { key: 'hasFlammableLiquids' as const, label: '💧 Flammable Liquids' },
                                { key: 'hasFlammableGases' as const, label: '⛽ Flammable Gases' },
                                { key: 'hasCombustibleMetals' as const, label: '🔩 Combustible Metals' },
                                { key: 'hasElectricalHazards' as const, label: '⚡ Electrical Hazards (server rooms, panels)' },
                            ].map((item) => (
                                <label key={item.key} className="flex items-center gap-3 cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={!!form[item.key]}
                                        onChange={(e) => updateField(item.key, e.target.checked)}
                                        className="w-4 h-4 rounded border-slate-300 text-orange-500 focus:ring-orange-400"
                                    />
                                    <span className="text-sm text-slate-600">{item.label}</span>
                                </label>
                            ))}
                        </div>
                    </div>

                    {/* Cooking area (conditional) */}
                    {form.hasKitchen && (
                        <div>
                            <label className="block text-sm font-medium text-slate-700 mb-1">
                                Cooking Appliance Area (m²)
                            </label>
                            <input
                                type="number"
                                value={form.cookingAreaM2 || ''}
                                onChange={(e) => updateField('cookingAreaM2', Number(e.target.value))}
                                min={0}
                                step={0.01}
                                className="w-full px-3 py-2 rounded-lg border border-slate-200 focus:border-orange-400 outline-none transition text-sm"
                            />
                        </div>
                    )}

                    {/* Error */}
                    {error && (
                        <div className="px-4 py-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
                            ⚠️ {error}
                        </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-3 pt-2">
                        <button
                            onClick={handleSubmit}
                            disabled={loading || !form.totalFloorArea}
                            className="btn-primary flex-1"
                        >
                            {loading ? (
                                <>
                                    <span className="spinner !w-4 !h-4 !border-white/30 !border-t-white"></span>
                                    Analyzing...
                                </>
                            ) : (
                                '✅ Confirm & Analyze'
                            )}
                        </button>
                        <button onClick={() => router.push('/')} className="btn-secondary">
                            ← Back
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default function ConfirmPage() {
    return (
        <main className="min-h-screen bg-[var(--background)]">
            <Navbar />
            <Suspense fallback={
                <div className="pt-32 pb-8 flex flex-col items-center justify-center">
                    <div className="spinner mb-4"></div>
                    <p className="text-slate-500">Loading form...</p>
                </div>
            }>
                <ConfirmForm />
            </Suspense>
            <Footer />
        </main>
    );
}
