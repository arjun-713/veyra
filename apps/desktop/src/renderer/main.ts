import {mount} from 'svelte';
import '@fontsource/space-grotesk/400.css';
import '@fontsource/space-grotesk/500.css';
import '@fontsource/space-grotesk/600.css';
import '@fontsource/space-grotesk/700.css';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
import './style.css';
import {installTauriAPI} from '../tauri-api';
installTauriAPI();
import {normalizeNavigatorLocale} from '../locale';

normalizeNavigatorLocale();
void import('./App.svelte').then(({default:App})=>{
 mount(App,{target:document.getElementById('app')!});
});
