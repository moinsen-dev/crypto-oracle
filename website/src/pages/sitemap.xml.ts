import type { APIRoute } from 'astro';

const pages = ['/', '/forecasts/', '/paper-portfolio/', '/evidence/', '/method/', '/build-notes/', '/newsletter/', '/privacy/', '/legal/'];

export const GET: APIRoute = ({ site }) => new Response(
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${pages.map(page => `  <url><loc>${new URL(page, site).href}</loc></url>`).join('\n')}\n</urlset>\n`,
  { headers: { 'Content-Type': 'application/xml; charset=utf-8' } },
);
