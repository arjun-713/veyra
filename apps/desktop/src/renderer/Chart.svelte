<script lang="ts">
 import {onMount} from 'svelte';import uPlot from 'uplot';import 'uplot/dist/uPlot.min.css';
 let {samples=[],metric='fps',label='FPS',color='#47d6ce'}=$props<{samples:Record<string,any>[];metric:string;label:string;color?:string}>();
 let host:HTMLDivElement,plot:uPlot|null=null;
 function data():uPlot.AlignedData{return [samples.map((s:Record<string,any>)=>s.timestamp),samples.map((s:Record<string,any>)=>typeof s[metric]==='number'?s[metric]:null)];}
 $effect(()=>{samples;metric;plot?.setData(data());});
 onMount(()=>{plot=new uPlot({width:host.clientWidth||500,height:180,legend:{show:false},cursor:{show:true},axes:[{stroke:'#6d8397',grid:{stroke:'#1d2b38'}},{stroke:'#6d8397',grid:{stroke:'#1d2b38'}}],series:[{}, {label,stroke:color,width:2,fill:color+'12'}]},data(),host);const resize=new ResizeObserver(()=>plot?.setSize({width:host.clientWidth,height:180}));resize.observe(host);return()=>{resize.disconnect();plot?.destroy();plot=null;};});
</script>
<div class="chart" bind:this={host}></div>
<style>.chart{width:100%;min-width:0;height:180px}</style>
