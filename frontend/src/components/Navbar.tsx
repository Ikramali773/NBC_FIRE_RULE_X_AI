'use client';

import Link from 'next/link';

export default function Navbar() {
    return (
        <nav className="fixed top-0 left-0 right-0 z-50 bg-white border-b border-slate-200">
            <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex items-center justify-between h-16">
                    <Link href="/" data-testid="nav-home" className="flex items-center gap-2 group">
                        <span className="w-6 h-6 bg-[#0A192F] flex items-center justify-center">
                            <span className="text-white text-[10px] font-bold tracking-wider">FR</span>
                        </span>
                        <span className="text-sm font-bold text-slate-900 tracking-tight">
                            FIRE<span className="text-[#2962FF]">RULEX</span>
                        </span>
                        <span className="hidden sm:inline text-[9px] font-mono text-slate-400 border-l border-slate-200 pl-2 uppercase tracking-widest">
                            NBC Part 4
                        </span>
                    </Link>

                    <div className="flex items-center gap-6">
                        <Link
                            href="/new-analysis"
                            data-testid="nav-analyze"
                            className="text-xs uppercase tracking-widest font-bold text-slate-700 hover:text-[#2962FF] transition-colors"
                        >
                            Analyze
                        </Link>
                        <Link
                            href="/new-analysis"
                            data-testid="nav-start"
                            className="text-xs px-4 py-2 bg-[#0A192F] text-white uppercase tracking-widest font-bold hover:bg-slate-800 transition-colors"
                        >
                            New Analysis
                        </Link>
                    </div>
                </div>
            </div>
        </nav>
    );
}
