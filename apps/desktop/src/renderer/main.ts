import {mount} from 'svelte';
import App from './App.svelte';
import './style.css';
import {installTauriAPI} from '../tauri-api';
installTauriAPI();
mount(App,{target:document.getElementById('app')!});
