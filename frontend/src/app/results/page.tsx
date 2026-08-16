'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import PlacementViewer from '@/components/PlacementViewer';
import type { AnalyzeResponse, ComplianceResultItem } from '@/types';

const API_URL = '';

const STATUS_STYLES: Record<
    string,
    { badge: string; dot: string; label: string }
> = {
    required: { badge: 'bg-[#FFEBEE] text-[#D50000] border-[#FFCDD2]', dot: 'bg-[#D50000]', label: 'REQUIRED' },
    not_required: { badge: 'bg-[#F5F5F5] text-[#616161] border-[#E0E0E0]', dot: 'bg-[#9E9E9E]', label: 'NOT REQUIRED' },
    conditional: { badge: 'bg-[#FFFDE7] text-[#F9A825] border-[#FFF59D]', dot: 'bg-[#F9A825]', label: 'CONDITIONAL' },
    insufficient_data: { badge: 'bg-[#E3F2FD] text-[#1565C0] border-[#BBDEFB]', dot: 'bg-[#1565C0]', label: 'DATA NEEDED' },
};

const SYSTEM_ORDER = [
    'fire_extinguisher',
    'hose_reel',
    'wet_riser',
    'down_comer',
    'yard_hydrant',
    'sprinkler_system',
    'manual_alarm',
    'auto_detection',
];

const QUANTITY_LABEL: Record<string, string> = {
    underground_tank_litres: 'Underground Static Tank',
    terrace_tank_litres: 'Terrace Tank',
    underground_pump_lpm: 'Underground Fire Pump',
    terrace_pump_lpm: 'Terrace Fire Pump',
};

function ResultsContent() {
    const router = useRouter();
    const [data, setData] = useState<AnalyzeResponse | null>(null);
    const [downloading, setDownloading] = useState(false);
    const [expandedRow, setExpandedRow] = useState<string | null>(null);
    const [showPlacement, setShowPlacement] = useState(false);

    useEffect(() => {
        const stored = sessionStorage.getItem('firerulx_result');
        if (!stored) {
            router.push('/manual');
            return;
        }
        try {
            setData(JSON.parse(stored));
        } catch {
            router.push('/manual');
        }
    }, [router]);

    if (!data) {
        return (
            <div className="pt-32 pb-8 flex items-center justify-center">
                <span className="text-slate-500 text-xs uppercase tracking-widest">Loading…</span>
            </div>
        );
    }

    const { extraction, analysis } = data;
    const items: ComplianceResultItem[] = (analysis.complianceItems || []).slice().sort(
        (a, b) => SYSTEM_ORDER.indexOf(a.id) - SYSTEM_ORDER.indexOf(b.id),
    );
    const mixed = analysis.mixedOccupancySummary;
    const isMixed = mixed?.mode === 'mixed';

    // Cost estimation for wet-riser and down-comer (very rough — INR/floor)
    const wetRiser = items.find((i) => i.id === 'wet_riser');
    const downComer = items.find((i) => i.id === 'down_comer');
    const wetRiserCost = wetRiser?.status === 'required' ? extraction.numberOfFloors * 180000 : 0;
    const downComerCost = downComer?.status === 'required' ? extraction.numberOfFloors * 95000 : 0;

    // Collect BIS map
    const bisMap: Record<string, string[]> = {};
    items.forEach((it) => {
        if (it.status !== 'required') return;
        it.bisStandards.forEach((s) => {
            if (!bisMap[s]) bisMap[s] = [];
            if (!bisMap[s].includes(it.title)) bisMap[s].push(it.title);
        });
    });

    const downloadPdf = async () => {
        setDownloading(true);
        try {
            const res = await fetch(`${API_URL}/api/reports/compliance.pdf`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payload: data }),
            });
            if (!res.ok) throw new Error('PDF generation failed');
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${extraction.projectName || extraction.buildingName || 'firerulex-report'}-compliance.pdf`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            alert(e instanceof Error ? e.message : 'PDF download failed');
        } finally {
            setDownloading(false);
        }
    };

    return (
        <div className="pt-24 pb-16 px-4 sm:px-6 lg:px-10">
            <div className="max-w-6xl mx-auto space-y-8">
                {/* Header row */}
                <header className="flex flex-col md:flex-row md:items-end md:justify-between gap-3" data-testid="results-header">
                    <div>
                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.25em]">Report · NBC Part 4</p>
                        <h1 className="text-3xl font-bold text-slate-900 tracking-tight mt-1">
                            {extraction.projectName || extraction.buildingName || 'Compliance Report'}
                        </h1>
                        <p className="text-sm text-slate-500 mt-1 font-mono">
                            {extraction.city || '—'}{extraction.city && extraction.state ? ', ' : ''}{extraction.state || ''}
                            {' · '}{new Date(data.meta.analyzedAt).toLocaleString()}
                        </p>
                    </div>
                    <div className="flex gap-2">
                        <button
                            data-testid="new-analysis-btn"
                            onClick={() => router.push('/manual')}
                            className="text-xs px-4 py-2 border border-slate-300 text-slate-700 hover:border-slate-800 uppercase tracking-widest font-bold"
                        >
                            ← New analysis
                        </button>
                        <button
                            data-testid="placement-open-btn"
                            onClick={() => setShowPlacement(true)}
                            className="text-xs px-4 py-2 border border-slate-300 text-slate-700 hover:border-slate-800 uppercase tracking-widest font-bold"
                        >
                            🧯 Suggest Extinguisher Placement
                        </button>
                        <button
                            data-testid="pdf-export-btn"
                            onClick={downloadPdf}
                            disabled={downloading}
                            className="text-xs px-4 py-2 bg-[#0A192F] text-white hover:bg-slate-800 disabled:opacity-40 uppercase tracking-widest font-bold"
                        >
                            {downloading ? 'Preparing…' : '⬇ Download PDF'}
                        </button>
                    </div>
                </header>

                {showPlacement && (
                    <PlacementViewer hazardType={analysis.hazardType} onClose={() => setShowPlacement(false)} />
                )}

                {/* SECTION 1: Building Summary */}
                <Section title="1. Building Information" testid="section-building-info">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-slate-200 border border-slate-200">
                        <SummaryStat label="Height" value={`${extraction.buildingHeight} m`} />
                        <SummaryStat label="Floors" value={String(extraction.numberOfFloors)} />
                        <SummaryStat label="Total Area" value={`${(extraction.totalFloorArea || 0).toLocaleString()} m²`} />
                        <SummaryStat label="Basement" value={extraction.basementArea ? `${extraction.basementArea.toLocaleString()} m²` : '—'} />
                    </div>

                    {/* Mixed occupancy chip strip */}
                    <div className="mt-4">
                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em] mb-2">
                            {isMixed ? 'Mixed Occupancy Composition' : 'Occupancy'}
                        </p>
                        <div className="flex flex-wrap gap-2" data-testid="occupancy-chips">
                            {(mixed?.occupancyCodes || (extraction.occupancySubdivision ? [extraction.occupancySubdivision] : []))
                                .map((code) => {
                                    const label = mixed?.occupancyLabels?.[code] || code;
                                    const tier = mixed?.heightTierLabels?.[code];
                                    return (
                                        <div
                                            key={code}
                                            data-testid={`occ-chip-${code}`}
                                            className="flex items-center gap-2 px-3 py-1.5 border border-slate-300 bg-white"
                                        >
                                            <span className="font-mono text-xs font-bold text-[#2962FF]">{code}</span>
                                            <span className="text-xs text-slate-800">{label}</span>
                                            {tier && (
                                                <span className="text-[10px] text-slate-500 border-l border-slate-200 pl-2">Tier {tier}</span>
                                            )}
                                        </div>
                                    );
                                })}
                        </div>
                    </div>
                </Section>

                {/* SECTION 2: NBC Compliance summary */}
                {analysis.nbcCompliance?.occupantLoad && (
                    <Section title="2. NBC Compliance — Occupant Load & Exits" testid="section-nbc">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-slate-200 border border-slate-200">
                            <SummaryStat label="Total Occupants" value={String(analysis.nbcCompliance.occupantLoad.totalOccupants)} />
                            <SummaryStat label="Load Factor" value={`${analysis.nbcCompliance.occupantLoad.loadFactor} m²/p`} />
                            {analysis.nbcCompliance.exitCapacity && (
                                <>
                                    <SummaryStat label="Max Stairway" value={`${analysis.nbcCompliance.exitCapacity.maxStairwayWidthMm} mm`} />
                                    <SummaryStat label="Max Door/Corridor" value={`${analysis.nbcCompliance.exitCapacity.maxLevelWidthMm} mm`} />
                                </>
                            )}
                        </div>
                        {analysis.nbcCompliance.travelDistance && (
                            <p className="text-xs text-slate-600 mt-3">
                                <span className="text-slate-400 uppercase tracking-wider text-[10px] font-bold mr-2">Travel distance</span>
                                Max allowed <span className="font-mono text-slate-900">{analysis.nbcCompliance.travelDistance.maxDistanceM} m</span>
                                {' '}(base <span className="font-mono">{analysis.nbcCompliance.travelDistance.baseDistanceM}</span>,
                                {analysis.nbcCompliance.travelDistance.sprinklerApplied ? ' sprinkler +50%' : ' no sprinkler bonus'})
                                {' · '}Group {analysis.nbcCompliance.travelDistance.group}, {analysis.nbcCompliance.travelDistance.constructionType}
                            </p>
                        )}
                    </Section>
                )}

                {/* SECTION 3: Fire-Fighting Installations */}
                <Section title="3. Fire-Fighting Installations (Table 7)" testid="section-installations">
                    <div className="border border-slate-200 overflow-x-auto">
                        <table className="w-full text-xs" data-testid="installations-table">
                            <thead>
                                <tr className="bg-[#0A192F] text-white text-[10px] uppercase tracking-widest">
                                    <th className="text-left px-3 py-2 font-semibold w-10"></th>
                                    <th className="text-left px-3 py-2 font-semibold">System</th>
                                    <th className="text-left px-3 py-2 font-semibold w-32">Status</th>
                                    <th className="text-left px-3 py-2 font-semibold">Reason</th>
                                    <th className="text-left px-3 py-2 font-semibold w-40">Triggered By</th>
                                </tr>
                            </thead>
                            <tbody>
                                {items.map((it) => {
                                    const isOpen = expandedRow === it.id;
                                    const s = STATUS_STYLES[it.status] || STATUS_STYLES.not_required;
                                    return (
                                        <>
                                            <tr
                                                key={it.id}
                                                data-testid={`row-${it.id}`}
                                                className={`border-t border-slate-100 cursor-pointer hover:bg-slate-50 ${isOpen ? 'bg-slate-50' : ''}`}
                                                onClick={() => setExpandedRow(isOpen ? null : it.id)}
                                            >
                                                <td className="px-3 py-2 text-slate-400 font-mono text-[10px]">{isOpen ? '▾' : '▸'}</td>
                                                <td className="px-3 py-2 font-semibold text-slate-900">{it.title}</td>
                                                <td className="px-3 py-2">
                                                    <span data-testid={`status-${it.id}`} className={`inline-flex items-center gap-1.5 px-2 py-0.5 border font-mono text-[10px] font-bold ${s.badge}`}>
                                                        <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                                                        {s.label}
                                                    </span>
                                                </td>
                                                <td className="px-3 py-2 text-slate-600 leading-relaxed">{it.reason}</td>
                                                <td className="px-3 py-2 font-mono text-[#2962FF]">
                                                    {it.triggeredBy.length > 0 ? it.triggeredBy.join(', ') : '—'}
                                                </td>
                                            </tr>
                                            {isOpen && (
                                                <tr className="bg-slate-50 border-t border-slate-100" data-testid={`row-detail-${it.id}`}>
                                                    <td colSpan={5} className="px-6 py-3">
                                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                                                            <div>
                                                                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Clause / Table / Note</p>
                                                                <ul className="space-y-0.5">
                                                                    {(it.clauseRefs.length ? it.clauseRefs : ['—']).map((c, i) => (
                                                                        <li key={i} className="font-mono text-[#2962FF]">{c}</li>
                                                                    ))}
                                                                </ul>
                                                            </div>
                                                            <div>
                                                                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">BIS Standards</p>
                                                                <div className="flex flex-wrap gap-1">
                                                                    {it.bisStandards.length > 0
                                                                        ? it.bisStandards.map((b) => (
                                                                              <span key={b} className="font-mono text-[10px] px-1.5 py-0.5 border border-slate-300 text-slate-800">{b}</span>
                                                                          ))
                                                                        : <span className="text-slate-400">—</span>}
                                                                </div>
                                                            </div>
                                                            <div>
                                                                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Next Steps</p>
                                                                <ul className="space-y-0.5 text-slate-700">
                                                                    {(it.nextSteps.length ? it.nextSteps : ['—']).map((n, i) => (
                                                                        <li key={i}>• {n}</li>
                                                                    ))}
                                                                </ul>
                                                            </div>
                                                        </div>
                                                        {it.notes.length > 0 && (
                                                            <div className="mt-3 pt-3 border-t border-slate-200">
                                                                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Triggered Notes</p>
                                                                <ul className="space-y-1 text-[11px] text-slate-600">
                                                                    {it.notes.map((n, i) => <li key={i} className="leading-relaxed">→ {n}</li>)}
                                                                </ul>
                                                            </div>
                                                        )}
                                                    </td>
                                                </tr>
                                            )}
                                        </>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </Section>

                {/* SECTION 4: Water Storage & Pumps + WR/DC cost */}
                {(analysis.aggregatedQuantities && Object.keys(analysis.aggregatedQuantities).length > 0) && (
                    <Section title="4. Water Storage & Pumps (strictest aggregated)" testid="section-quantities">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div className="border border-slate-200">
                                <table className="w-full text-xs">
                                    <thead>
                                        <tr className="bg-slate-100 text-[10px] uppercase tracking-widest text-slate-500">
                                            <th className="text-left px-3 py-2">Quantity</th>
                                            <th className="text-right px-3 py-2">Value</th>
                                            <th className="text-left px-3 py-2">Triggered by</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {Object.entries(analysis.aggregatedQuantities).map(([k, v]) => (
                                            <tr key={k} className="border-t border-slate-100">
                                                <td className="px-3 py-2 text-slate-900">{QUANTITY_LABEL[k] || k}</td>
                                                <td className="px-3 py-2 text-right font-mono">{v.value.toLocaleString()} {v.unit}</td>
                                                <td className="px-3 py-2 font-mono text-[#2962FF]">{v.triggeredBy.join(', ')}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            <div className="border border-slate-200 p-4 space-y-3">
                                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em]">
                                    Indicative cost — Wet Riser vs Down Comer
                                </p>
                                <div className="space-y-2 text-xs">
                                    <CostRow
                                        label="Wet Riser (100 mm shaft, landing valves, hose cabinets)"
                                        required={wetRiser?.status === 'required'}
                                        cost={wetRiserCost}
                                    />
                                    <CostRow
                                        label="Down Comer (100 mm shaft, landing valves, terrace connection)"
                                        required={downComer?.status === 'required'}
                                        cost={downComerCost}
                                    />
                                </div>
                                <p className="text-[10px] text-slate-400 leading-relaxed">
                                    Rough order-of-magnitude estimate — validate with a BOQ from a licensed fire consultant.
                                </p>
                            </div>
                        </div>
                    </Section>
                )}

                {/* SECTION 5-6-7: PC / MI / NS */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <ListPanel
                        title="5. Passed Checks"
                        testid="section-passed"
                        color="bg-[#E8F5E9] text-[#00C853] border-[#C8E6C9]"
                        items={analysis.passedChecks || analysis.passedRules || []}
                    />
                    <ListPanel
                        title="6. Missing Inputs"
                        testid="section-missing"
                        color="bg-[#FFFDE7] text-[#F9A825] border-[#FFF59D]"
                        items={analysis.missingInputs || []}
                        emptyMessage="No missing inputs — all evaluations complete."
                    />
                    <ListPanel
                        title="7. Next Steps"
                        testid="section-next-steps"
                        color="bg-[#E3F2FD] text-[#1565C0] border-[#BBDEFB]"
                        items={analysis.nextSteps || []}
                    />
                </div>

                {/* SECTION 8: Triggered BIS Standards */}
                {Object.keys(bisMap).length > 0 && (
                    <Section title="8. Triggered BIS Standards" testid="section-bis">
                        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                            {Object.entries(bisMap).sort().map(([std, triggers]) => (
                                <div
                                    key={std}
                                    data-testid={`bis-${std.replace(/\s/g, '-')}`}
                                    className="border border-slate-200 p-3"
                                >
                                    <p className="font-mono text-sm font-bold text-[#2962FF]">{std}</p>
                                    <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-2 mb-1">Triggered by</p>
                                    <p className="text-xs text-slate-800 leading-snug">{triggers.join(', ')}</p>
                                </div>
                            ))}
                        </div>
                    </Section>
                )}

                {/* SECTION 9: Disclaimer */}
                <Section title="9. Disclaimer" testid="section-disclaimer">
                    <p className="text-xs text-slate-600 leading-relaxed">
                        This report is an advisory pre-check aligned with NBC 2016 Part 4 (Fire and Life Safety) and does not
                        replace formal Fire NOC review by the local Chief Fire Officer / AHJ. Design decisions must be validated
                        by a qualified fire-safety consultant and cross-checked against state fire-service rules, latest NBC
                        amendments, and jurisdictional bye-laws before construction.
                    </p>
                </Section>
            </div>
        </div>
    );
}

// ── Small presentational sub-components ────────────────────────────

function Section({ title, testid, children }: { title: string; testid?: string; children: React.ReactNode }) {
    return (
        <section data-testid={testid} className="bg-white border border-slate-200">
            <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-900 uppercase tracking-[0.15em]">{title}</h2>
            </div>
            <div className="p-5">{children}</div>
        </section>
    );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
    return (
        <div className="bg-white px-4 py-3">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em]">{label}</p>
            <p className="font-mono text-lg text-slate-900 mt-0.5">{value}</p>
        </div>
    );
}

function ListPanel({
    title, items, color, emptyMessage, testid,
}: {
    title: string; items: string[]; color: string; emptyMessage?: string; testid?: string;
}) {
    return (
        <section data-testid={testid} className="bg-white border border-slate-200">
            <div className={`px-5 py-3 border-b border-slate-200 flex items-center gap-2 ${color}`}>
                <h2 className="text-sm font-bold uppercase tracking-[0.15em]">{title}</h2>
            </div>
            <div className="p-5">
                {items.length === 0 ? (
                    <p className="text-xs text-slate-400">{emptyMessage || '— None —'}</p>
                ) : (
                    <ul className="space-y-2 text-xs text-slate-700">
                        {items.map((s, i) => (
                            <li key={i} className="leading-relaxed border-l-2 border-slate-200 pl-2">{s}</li>
                        ))}
                    </ul>
                )}
            </div>
        </section>
    );
}

function CostRow({ label, required, cost }: { label: string; required: boolean; cost: number }) {
    return (
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 pb-2">
            <div className="flex-1">
                <p className="text-slate-800 leading-tight">{label}</p>
                <p className={`text-[10px] uppercase tracking-widest font-bold mt-0.5 ${required ? 'text-[#D50000]' : 'text-slate-400'}`}>
                    {required ? 'Required' : 'Not required'}
                </p>
            </div>
            <div className="text-right font-mono">
                <p className={`text-sm ${required ? 'text-slate-900' : 'text-slate-400'}`}>
                    {required ? `₹${cost.toLocaleString('en-IN')}` : '—'}
                </p>
            </div>
        </div>
    );
}

export default function ResultsPage() {
    return (
        <main className="min-h-screen bg-[#F8F9FA]">
            <Navbar />
            <Suspense fallback={<div className="pt-32 text-center text-slate-500">Loading…</div>}>
                <ResultsContent />
            </Suspense>
            <Footer />
        </main>
    );
}
