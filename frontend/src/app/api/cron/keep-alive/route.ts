import { NextResponse } from 'next/server';

export async function GET(request: Request) {
    // Basic security: optional Cron secret setup
    // Vercel sends a CRON_SECRET header with the secret defined in the Vercel dashboard.
    // If you add CRON_SECRET to your Vercel env, uncomment the lines below for strict security.
    /*
    const authHeader = request.headers.get('authorization');
    if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
        return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    */

    let API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    if (API_BASE_URL && !API_BASE_URL.startsWith('http')) {
        API_BASE_URL = `https://${API_BASE_URL}`;
    }
    
    try {
        // Hit the root endpoint of your backend (fastapi root) to wake it up
        const response = await fetch(`${API_BASE_URL}/`, {
            method: 'GET',
            headers: { 'Cache-Control': 'no-cache' }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        return NextResponse.json({ success: true, message: 'Backend kept alive', data });
        
    } catch (error) {
        console.error('Keep-alive failed:', error);
        return NextResponse.json(
            { success: false, error: (error as Error).message }, 
            { status: 500 }
        );
    }
}
