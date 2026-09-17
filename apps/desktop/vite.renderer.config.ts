import {defineConfig} from 'vite';
import {svelte} from '@sveltejs/vite-plugin-svelte';
export default defineConfig({plugins:[svelte()],base:'./',build:{emptyOutDir:true,rollupOptions:{output:{manualChunks:{three:['three'],charts:['uplot']}}}},server:{host:'127.0.0.1',port:1420,strictPort:true}});
