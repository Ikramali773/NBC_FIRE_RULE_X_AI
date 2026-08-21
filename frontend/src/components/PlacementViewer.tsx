'use client';

// Phase 3a — Automated Equipment Placement (fire extinguishers, dots only).
//
// Renders the uploaded plan PDF to a canvas (pdfjs-dist — no PDF viewer
// existed anywhere in this app before this component) and overlays the
// backend's suggested extinguisher positions at the same coordinates the
// backend measured them in. pdfplumber (backend) already reports word/shape
// positions as "top-down" (top = distance from the page's TOP edge), which
// is the same convention a canvas uses (y increases downward) — so canvas
// position is a single linear scale from PDF points to canvas pixels, no
// separate coordinate-flip needed, as long as the canvas is rendered at a
// known scale from the same page dimensions returned by the API.
//
// Multi-floor: the backend auto-detects every floor page in the uploaded
// file (POST /api/placement/suggest-floors) and returns one result per
// floor that could be placed — a floor whose scale can't be calibrated is
// skipped there with a specific reason, surfaced below as a warning rather
// than hidden. The floor-tab row lets the user switch which floor's canvas
// + table is shown; only ONE floor's PDF page is ever rendered at a time.
//
// No pipe-routing lines, no other equipment types, no styled export — this
// is an in-app overlay only, per Phase 3a's stated scope.

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PlacementFloorResult, PlacementSuggestFloorsResponse } from '@/types';

const CONF_COLORS: Record<string, { bg: string; border: string; text: string }> = {
    green: { bg: '#E8F5E9', border: '#4CAF50', text: '#2E7D32' },
    amber: { bg: '#FFF8E1', border: '#FFB300', text: '#F57F17' },
    red: { bg: '#FFEBEE', border: '#E53935', text: '#C62828' },
};

export default function PlacementViewer({ hazardType, onClose }: { hazardType: string; onClose: () => void }) {
    const [step, setStep] = useState<'upload' | 'processing' | 'result' | 'error'>('upload');
    const [error, setError] = useState('');
    const [floors, setFloors] = useState<PlacementFloorResult[]>([]);
    const [skippedFloorWarnings, setSkippedFloorWarnings] = useState<string[]>([]);
    const [activeTab, setActiveTab] = useState(0);
    const [manualMmPerPt, setManualMmPerPt] = useState<string>('');
    const [pdfBytes, setPdfBytes] = useState<Uint8Array | null>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    const activeFloor = floors[activeTab] ?? null;

    const runSuggestion = useCallback(async (file: File) => {
        setStep('processing');
        setError('');
        try {
            const buf = await file.arrayBuffer();
            setPdfBytes(new Uint8Array(buf.slice(0)));

            let API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
            if (API_URL && !API_URL.startsWith('http')) API_URL = `https://${API_URL}`;

            const formData = new FormData();
            formData.append('file', file);
            formData.append('hazard_type', hazardType);

            const res = await fetch(`${API_URL}/api/placement/suggest-floors`, {
                method: 'POST',
                body: formData,
                // Every floor page now runs the full geometry/scale chain
                // sequentially server-side (the old single-page endpoint's
                // 120s budget assumed one page) — a real 5-floor file can
                // genuinely take several minutes.
                signal: AbortSignal.timeout(360000),
            });
            const data: PlacementSuggestFloorsResponse & { error?: string } = await res.json();
            if (!res.ok) {
                throw new Error(data.error || 'Placement suggestion failed.');
            }
            setFloors(data.floors);
            setSkippedFloorWarnings(data.warnings || []);
            setActiveTab(0);
            const firstScale = data.floors[0]?.scale?.mm_per_pt;
            setManualMmPerPt(firstScale ? String(Math.round(firstScale * 100) / 100) : '');
            setStep('result');
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Placement suggestion failed.');
            setStep('error');
        }
    }, [hazardType]);

    const handleFile = useCallback((f: File) => {
        if (!f.name.toLowerCase().endsWith('.pdf')) {
            setError('Only PDF files are supported for automated placement.');
            setStep('error');
            return;
        }
        runSuggestion(f);
    }, [runSuggestion]);

    // Switching floor tabs re-syncs the editable scale field to the newly
    // active floor's own calibration, so it never shows a stale value from
    // whichever floor was previously selected.
    useEffect(() => {
        const mm = activeFloor?.scale?.mm_per_pt;
        setManualMmPerPt(mm ? String(Math.round(mm * 100) / 100) : '');
    }, [activeTab, activeFloor]);

    // Render the PDF page + dot overlay for the currently active floor.
    useEffect(() => {
        if (!pdfBytes || !activeFloor || step !== 'result' || !canvasRef.current) return;
        let cancelled = false;

        (async () => {
            const pdfjsLib = await import('pdfjs-dist');
            pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
                'pdfjs-dist/build/pdf.worker.min.mjs',
                import.meta.url,
            ).toString();

            const doc = await pdfjsLib.getDocument({ data: pdfBytes.slice() }).promise;
            const page = await doc.getPage(activeFloor.pageIndex + 1);

            const targetWidthPx = 900;
            const scale = targetWidthPx / activeFloor.pageWidthPt;
            const viewport = page.getViewport({ scale });

            const canvas = canvasRef.current;
            if (!canvas || cancelled) return;
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            await page.render({ canvasContext: ctx, viewport }).promise;
            if (cancelled) return;

            // Dot overlay — same linear scale as the canvas render, since
            // xPt/yPt are already top-down like the canvas's own y-axis.
            activeFloor.points.forEach((p) => {
                const x = p.xPt * scale;
                const y = p.yPt * scale;
                ctx.beginPath();
                ctx.arc(x, y, p.isJunction ? 9 : 7, 0, 2 * Math.PI);
                ctx.fillStyle = '#D50000';
                ctx.fill();
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = '#ffffff';
                ctx.stroke();
                ctx.fillStyle = '#ffffff';
                ctx.font = 'bold 10px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(String(p.index), x, y);
            });
        })();

        return () => { cancelled = true; };
    }, [pdfBytes, activeFloor, step]);

    const scaleConf = activeFloor?.scale.confidence || 'red';
    const colors = CONF_COLORS[scaleConf];

    return (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-8 pb-8 overflow-y-auto">
            <div className="bg-white w-full max-w-5xl border border-slate-200 shadow-xl mx-4">
                <div className="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                    <div>
                        <h2 className="text-lg font-bold text-slate-900">Suggested Fire Extinguisher Placement</h2>
                        <p className="text-xs text-slate-500 mt-0.5">
                            Phase 3a · Dots only · Fire extinguishers only · Requires a CAD-drawn PDF with real line geometry
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-xs text-slate-500 hover:text-slate-800 underline underline-offset-4"
                        data-testid="placement-close"
                    >
                        Close
                    </button>
                </div>

                {step === 'upload' && (
                    <div className="p-8">
                        <div
                            className="border-2 border-dashed border-slate-300 bg-white hover:border-slate-400 p-12 text-center cursor-pointer transition-all"
                            onClick={() => inputRef.current?.click()}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                                e.preventDefault();
                                if (e.dataTransfer.files?.[0]) handleFile(e.dataTransfer.files[0]);
                            }}
                        >
                            <input
                                ref={inputRef}
                                type="file"
                                accept=".pdf"
                                className="hidden"
                                onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }}
                            />
                            <div className="text-5xl opacity-60 mb-4">📐</div>
                            <p className="text-lg font-semibold text-slate-600">Drop a vector PDF floor plan here</p>
                            <p className="text-sm text-slate-400 mt-1">or click to browse · PDF only · every floor page in the file is detected and analyzed</p>
                        </div>
                        <p className="text-xs text-slate-400 mt-4 leading-relaxed">
                            This feature needs a CAD-drawn file with real vector line data — scanned or photographed
                            plans aren&apos;t supported. Hazard level used: <span className="font-mono text-slate-600">{hazardType}</span> (from this analysis).
                        </p>
                    </div>
                )}

                {step === 'processing' && (
                    <div className="p-16 text-center">
                        <div className="w-12 h-12 border-3 border-slate-200 border-t-[#0A192F] rounded-full animate-spin mx-auto mb-6" />
                        <p className="text-sm text-slate-600">Extracting wall geometry, building the walkable graph, calibrating scale…</p>
                    </div>
                )}

                {step === 'error' && (
                    <div className="p-8 text-center">
                        <div className="text-4xl mb-4">⚠️</div>
                        <p className="text-sm text-red-600 mb-6">{error}</p>
                        <button
                            onClick={() => { setStep('upload'); setError(''); }}
                            className="bg-[#0A192F] text-white py-2.5 px-6 text-xs uppercase tracking-widest font-bold hover:bg-slate-800"
                        >
                            Try a Different File
                        </button>
                    </div>
                )}

                {step === 'result' && activeFloor && (
                    <div>
                        {floors.length > 1 && (
                            <div className="flex flex-wrap gap-1.5 px-4 pt-4 border-b border-slate-100 pb-3" data-testid="floor-tabs">
                                {floors.map((f, i) => (
                                    <button
                                        key={`${f.floorLabel}-${f.pageIndex}`}
                                        onClick={() => setActiveTab(i)}
                                        className={`px-3 py-1.5 text-xs font-bold uppercase tracking-wide border ${
                                            i === activeTab
                                                ? 'bg-[#0A192F] text-white border-[#0A192F]'
                                                : 'bg-white text-slate-600 border-slate-300 hover:border-slate-400'
                                        }`}
                                        data-testid={`floor-tab-${i}`}
                                    >
                                        {f.floorLabel}
                                    </button>
                                ))}
                            </div>
                        )}

                        {skippedFloorWarnings.length > 0 && (
                            <div className="mx-4 mt-3 px-3 py-2 bg-amber-50 border border-amber-200 text-[11px] text-amber-700 space-y-1">
                                <p className="font-bold uppercase tracking-wider text-[10px]">Some floors were skipped</p>
                                {skippedFloorWarnings.map((w, i) => <p key={i}>• {w}</p>)}
                            </div>
                        )}

                        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px]">
                            <div className="p-4 border-r border-slate-100 overflow-auto max-h-[75vh] flex justify-center bg-slate-50">
                                <canvas ref={canvasRef} className="border border-slate-300 bg-white shadow-sm" data-testid="placement-canvas" />
                            </div>

                            <div className="p-4 max-h-[75vh] overflow-auto space-y-4">
                                <div
                                    className="px-3 py-2.5 text-xs"
                                    style={{ backgroundColor: colors.bg, borderLeft: `3px solid ${colors.border}` }}
                                >
                                    <p className="font-bold uppercase tracking-wider text-[10px] mb-1" style={{ color: colors.text }}>
                                        Drawing Scale — {scaleConf === 'green' ? 'High confidence' : scaleConf === 'amber' ? 'Verify' : 'Not detected'}
                                    </p>
                                    <div className="flex items-center gap-2">
                                        <input
                                            type="number"
                                            step="0.01"
                                            value={manualMmPerPt}
                                            onChange={(e) => setManualMmPerPt(e.target.value)}
                                            className="w-24 px-2 py-1 border border-slate-300 text-sm font-mono"
                                            data-testid="scale-mm-per-pt"
                                        />
                                        <span className="text-slate-500">mm / pt</span>
                                    </div>
                                    <p className="text-[11px] text-slate-500 mt-1 leading-snug">{activeFloor.scale.note}</p>
                                </div>

                                <div className="text-xs text-slate-600 space-y-1 border-b border-slate-100 pb-3">
                                    <p><span className="font-bold text-slate-400 uppercase tracking-wider text-[10px] mr-2">Floor</span>{activeFloor.floorLabel}</p>
                                    <p><span className="font-bold text-slate-400 uppercase tracking-wider text-[10px] mr-2">Hazard</span>{activeFloor.hazardType} → {activeFloor.rating}, max {activeFloor.maxAreaM2} m²/extinguisher</p>
                                    <p><span className="font-bold text-slate-400 uppercase tracking-wider text-[10px] mr-2">Coverage radius</span>{activeFloor.coverageRadiusM} m</p>
                                    <p><span className="font-bold text-slate-400 uppercase tracking-wider text-[10px] mr-2">Suggested points</span>{activeFloor.points.length}</p>
                                </div>

                                {activeFloor.warnings.length > 0 && (
                                    <div className="px-3 py-2 bg-amber-50 border border-amber-200 text-[11px] text-amber-700 space-y-1">
                                        {activeFloor.warnings.map((w, i) => <p key={i}>• {w}</p>)}
                                    </div>
                                )}

                                <div>
                                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em] mb-2">Suggested Locations</p>
                                    <div className="space-y-1.5" data-testid="placement-table">
                                        {activeFloor.points.map((p) => (
                                            <div key={p.index} className="flex items-start gap-2 text-xs border-b border-slate-100 pb-1.5">
                                                <span className="w-5 h-5 shrink-0 rounded-full bg-[#D50000] text-white text-[10px] font-bold flex items-center justify-center">{p.index}</span>
                                                <div className="min-w-0">
                                                    <p className="text-slate-800 truncate">{p.locationDescription}{p.isJunction ? ' · corridor junction' : ''}</p>
                                                    <p className="text-[10px] text-slate-400 font-mono">{p.clauseRef}</p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <button
                                    onClick={() => { setStep('upload'); setFloors([]); setSkippedFloorWarnings([]); setPdfBytes(null); }}
                                    className="w-full border border-slate-300 text-slate-700 py-2.5 text-xs uppercase tracking-widest font-bold hover:border-[#0A192F]"
                                >
                                    ← Try a Different File
                                </button>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
