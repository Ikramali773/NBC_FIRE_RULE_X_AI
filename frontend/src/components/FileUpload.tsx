'use client';

import { useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';

const ACCEPTED_TYPES = [
    'image/png',
    'image/jpeg',
    'image/jpg',
    'application/pdf',
    'image/vnd.dwg',
    'application/acad',
    'application/x-dwg',
    'application/dxf',
];

const ACCEPTED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.pdf', '.dwg', '.dxf'];
const MAX_SIZE = 10 * 1024 * 1024; // 10MB

function getFileExtension(name: string): string {
    return name.toLowerCase().slice(name.lastIndexOf('.'));
}

function isValidFile(file: File): { valid: boolean; error?: string } {
    const ext = getFileExtension(file.name);
    if (!ACCEPTED_TYPES.includes(file.type) && !ACCEPTED_EXTENSIONS.includes(ext)) {
        return { valid: false, error: `Unsupported file type. Accepted: ${ACCEPTED_EXTENSIONS.join(', ')}` };
    }
    if (file.size > MAX_SIZE) {
        return { valid: false, error: `File too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Max 10MB.` };
    }
    return { valid: true };
}

export default function FileUpload() {
    const [files, setFiles] = useState<File[]>([]);
    const [dragOver, setDragOver] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [loadingStep, setLoadingStep] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const router = useRouter();

    const handleFiles = useCallback((newFiles: FileList | File[]) => {
        setError(null);
        const validFiles: File[] = [];
        for (let i = 0; i < newFiles.length; i++) {
            const f = newFiles[i];
            const validation = isValidFile(f);
            if (!validation.valid) {
                setError(`${f.name}: ${validation.error}`);
                setFiles([]);
                return;
            }
            validFiles.push(f);
        }
        if (validFiles.length > 0) {
            setFiles(validFiles);
        }
    }, []);

    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            setDragOver(false);
            if (e.dataTransfer.files?.length > 0) {
                handleFiles(e.dataTransfer.files);
            }
        },
        [handleFiles]
    );

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files?.length) {
            handleFiles(e.target.files);
        }
    };

    const handleAnalyze = async () => {
        if (files.length === 0) return;
        setLoading(true);
        setError(null);
        setLoadingStep(1);

        try {
            const formData = new FormData();
            files.forEach(f => formData.append('file', f));

            // Step progression for UX
            const stepTimer1 = setTimeout(() => setLoadingStep(2), 3000);
            const stepTimer2 = setTimeout(() => setLoadingStep(3), 8000);
            const stepTimer3 = setTimeout(() => setLoadingStep(4), 15000);

            let API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
            if (API_BASE_URL && !API_BASE_URL.startsWith('http')) {
                API_BASE_URL = `https://${API_BASE_URL}`;
            }
            const response = await fetch(`${API_BASE_URL}/api/analyze`, {
                method: 'POST',
                body: formData,
                signal: AbortSignal.timeout(300000), // 300s timeout to allow multi-page PDF processing
            });

            clearTimeout(stepTimer1);
            clearTimeout(stepTimer2);
            clearTimeout(stepTimer3);

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || `Analysis failed (${response.status})`);
            }

            const data = await response.json();

            // Store result in sessionStorage for the results page
            sessionStorage.setItem('firerulx_result', JSON.stringify(data));

            // Route based on confidence
            if (data.needsConfirmation) {
                router.push('/confirm');
            } else {
                router.push('/results');
            }
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Analysis failed. Please try again.';
            setError(msg);
        } finally {
            setLoading(false);
            setLoadingStep(0);
        }
    };

    const loadingSteps = [
        '',
        '📤 Uploading your floor plan...',
        '🔄 Converting file to image...',
        '🧠 AI is analyzing your floor plan...',
        '📋 Running IS 2190:2024 compliance checks...',
    ];

    const formatSize = (bytes: number) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    if (loading) {
        return (
            <div className="card card-elevated text-center py-12 px-6">
                <div className="spinner spinner-lg mx-auto mb-6"></div>
                <p className="text-lg font-semibold text-slate-700 mb-2 animate-fade-in-up">
                    {loadingSteps[loadingStep]}
                </p>
                <p className="text-sm text-slate-400">Usually takes 15–30 seconds</p>
                <button
                    onClick={() => { setLoading(false); setLoadingStep(0); }}
                    className="mt-6 text-sm text-slate-400 hover:text-slate-600 underline transition-colors"
                >
                    Cancel
                </button>
            </div>
        );
    }

    return (
        <div>
            {/* Drop zone */}
            <div
                id="upload-zone"
                className={`upload-zone ${dragOver ? 'drag-over' : ''} ${files.length > 0 ? 'has-file' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => inputRef.current?.click()}
            >
                <input
                    ref={inputRef}
                    type="file"
                    multiple
                    accept={ACCEPTED_EXTENSIONS.join(',')}
                    onChange={handleChange}
                    className="hidden"
                    id="file-input"
                />

                {files.length > 0 ? (
                    <div className="space-y-2">
                        <div className="text-4xl">✅</div>
                        <p className="text-lg font-semibold text-slate-700">
                            {files.length === 1 ? files[0].name : `${files.length} files selected`}
                        </p>
                        <p className="text-sm text-slate-400">
                            {formatSize(files.reduce((acc, f) => acc + f.size, 0))} total
                        </p>
                        <p className="text-xs text-emerald-600 font-medium">Ready to analyze. Click &quot;Analyze&quot; below.</p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        <div className="text-5xl opacity-60">📐</div>
                        <p className="text-lg font-semibold text-slate-600">
                            Drop your floor plan here
                        </p>
                        <p className="text-sm text-slate-400">
                            or click to browse • DWG, PDF, JPG, PNG • Max 10MB
                        </p>
                    </div>
                )}
            </div>

            {/* Error message */}
            {error && (
                <div className="mt-3 px-4 py-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
                    ⚠️ {error}
                </div>
            )}

            {/* Analyze button */}
            <button
                id="analyze-btn"
                className="btn-primary w-full mt-4 py-4 text-lg animate-pulse-glow"
                onClick={handleAnalyze}
                disabled={files.length === 0 || loading}
            >
                🔍 Analyze Compliance
            </button>

            {/* Also offer manual input */}
            <button
                id="manual-input-btn"
                className="btn-secondary w-full mt-3"
                onClick={() => router.push('/manual')}
            >
                ✏️ Enter building data manually
            </button>
        </div>
    );
}
