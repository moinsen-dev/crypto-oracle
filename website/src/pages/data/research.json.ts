import type { APIRoute } from 'astro';
import research from '../../data/research.json';

export const GET: APIRoute = () => new Response(JSON.stringify(research, null, 2), {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
});
