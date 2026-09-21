import type { APIRoute } from 'astro';
import study from '../../data/momentum-study.json';

export const GET: APIRoute = () => new Response(JSON.stringify(study, null, 2), {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
});
