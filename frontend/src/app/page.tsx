'use client';

import Link from 'next/link';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';

export default function Home() {
    return (
        <main className="min-h-screen bg-[#F8F9FA]">
            <Navbar />

            {/* Hero */}
            <section className="pt-28 pb-12 px-4 sm:px-6 lg:px-10">
                <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-12 gap-8 items-end">
                    <div className="md:col-span-8">
                        <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.3em]">FireRuleX · NBC 2016 Part 4</p>
                        <h1 className="text-4xl md:text-5xl font-bold text-slate-900 leading-tight tracking-tight mt-3">
                            Fire &amp; Life Safety Compliance,{' '}
                            <span className="text-[#2962FF]">rule-engine grade.</span>
                        </h1>
                        <p className="mt-4 text-slate-600 text-base leading-relaxed max-w-2xl">
                            Model your building — single or mixed occupancy — and get a normalised NBC Part 4
                            compliance report with separate outputs for <span className="font-semibold text-slate-800">wet riser</span>,{' '}
                            <span className="font-semibold text-slate-800">down comer</span>, and every other fire system.
                        </p>
                        <div className="mt-6 flex flex-wrap items-center gap-3">
                            <Link
                                href="/new-analysis"
                                data-testid="cta-start-analysis"
                                className="inline-flex items-center gap-2 bg-[#0A192F] text-white px-5 py-3 text-xs uppercase tracking-widest font-bold hover:bg-slate-800"
                            >
                                Start Building Analysis →
                            </Link>
                            <a
                                href="#capabilities"
                                className="text-xs uppercase tracking-widest font-bold text-slate-700 hover:text-slate-900 underline underline-offset-4"
                            >
                                See what it checks
                            </a>
                        </div>
                    </div>

                    <div className="md:col-span-4">
                        <div className="border border-slate-200 bg-white p-5">
                            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-[0.25em]">Coverage</p>
                            <ul className="mt-3 space-y-2 text-xs text-slate-700 font-mono">
                                <li className="flex justify-between border-b border-slate-100 pb-1"><span>Table 7</span><span className="text-slate-400">Firefighting installations</span></li>
                                <li className="flex justify-between border-b border-slate-100 pb-1"><span>Table 3–5</span><span className="text-slate-400">Occupant load / exit / travel</span></li>
                                <li className="flex justify-between border-b border-slate-100 pb-1"><span>Mixed</span><span className="text-slate-400">2+ occupancy combos</span></li>
                                <li className="flex justify-between border-b border-slate-100 pb-1"><span>BIS</span><span className="text-slate-400">IS 2190, 3844, 15301…</span></li>
                                <li className="flex justify-between"><span>PDF</span><span className="text-slate-400">Server-side export</span></li>
                            </ul>
                        </div>
                    </div>
                </div>
            </section>

            {/* Capabilities strip */}
            <section id="capabilities" className="border-y border-slate-200 bg-white">
                <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-10 py-10 grid grid-cols-1 md:grid-cols-3 gap-6">
                    <Capability
                        idx="01"
                        title="Wet Riser & Down Comer — separated"
                        body="Each system is evaluated, reasoned and reported as a distinct row. No more collapsed vertical-riser row."
                    />
                    <Capability
                        idx="02"
                        title="Mixed occupancy resolver"
                        body="Enter 2+ occupancies (e.g. Hotel + Banquet). The engine applies the strictest NBC requirement per parameter and shows the triggering source."
                    />
                    <Capability
                        idx="03"
                        title="safety-calc-india style report"
                        body="Building summary, sectioned compliance blocks, Required/Not Required/Conditional badges, expandable NBC clause references, passed / missing / next-step lists, and a server-side PDF export."
                    />
                </div>
            </section>

            {/* How it works */}
            <section id="how-it-works" className="py-14 px-4 sm:px-6 lg:px-10">
                <div className="max-w-5xl mx-auto">
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-[0.3em]">Workflow</p>
                    <h2 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">Three steps to a compliance report</h2>
                    <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-px bg-slate-200 border border-slate-200">
                        <Step n="01" title="Occupancy" body="Single or mixed. Search by keyword, pick presets like Hotel + Restaurant, or attach floor/area zones." />
                        <Step n="02" title="Parameters" body="Enter height, floors, per-floor areas, basement, construction type. Live summary on the right." />
                        <Step n="03" title="Report" body="Compliance table, separate wet-riser & down-comer results, triggered BIS standards, PDF export." />
                    </div>
                </div>
            </section>

            <Footer />
        </main>
    );
}

function Capability({ idx, title, body }: { idx: string; title: string; body: string }) {
    return (
        <div className="border-l-2 border-[#0A192F] pl-4">
            <p className="text-[10px] font-mono text-slate-400">{idx}</p>
            <h3 className="text-sm font-bold text-slate-900 mt-1 leading-snug">{title}</h3>
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">{body}</p>
        </div>
    );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
    return (
        <div className="bg-white p-5">
            <p className="font-mono text-2xl text-[#2962FF] font-bold">{n}</p>
            <h3 className="text-sm font-bold text-slate-900 mt-1">{title}</h3>
            <p className="text-xs text-slate-600 mt-2 leading-relaxed">{body}</p>
        </div>
    );
}
