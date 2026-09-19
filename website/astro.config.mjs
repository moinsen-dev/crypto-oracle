import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  site: process.env.SITE_ORIGIN || 'https://cryptooracle.moinsen.dev',
  trailingSlash: 'always',
  build: { inlineStylesheets: 'never' },
  vite: { build: { assetsInlineLimit: 0, sourcemap: false } },
  devToolbar: { enabled: false },
});
