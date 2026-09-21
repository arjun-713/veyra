import {mount} from 'svelte';
import './style.css';
import {installTauriAPI} from '../tauri-api';
installTauriAPI();
import {normalizeNavigatorLocale} from '../locale';

normalizeNavigatorLocale();
void import('./App.svelte').then(({default:App})=>{
 mount(App,{target:document.getElementById('app')!});
});
