<script lang="ts">
 import {onMount} from 'svelte';import uPlot from 'uplot';import 'uplot/dist/uPlot.min.css';
 import {LIVE_TIME_TICKS,relativeChartSeries,type LiveMetric,type LiveTelemetrySample} from './live-telemetry';
 let {samples=[],metric='fps',label='FPS',color,emptyMessage='Waiting for live telemetry…',unavailableMessage='Unavailable in current telemetry'}=$props<{samples:LiveTelemetrySample[];metric:LiveMetric;label:string;color?:string;emptyMessage?:string;unavailableMessage?:string}>();
 let host:HTMLDivElement,plot:uPlot|null=null;
 function data():uPlot.AlignedData{const series=relativeChartSeries(samples,metric);return [series.x,series.y];}
 const xValues=(_plot:uPlot,values:number[])=>values.map(value=>LIVE_TIME_TICKS.find(tick=>tick.value===value)?.label??'');
 function token(name:string){return getComputedStyle(document.documentElement).getPropertyValue(name).trim();}
 function hasValue(rows:LiveTelemetrySample[],key:LiveMetric){return rows.some(row=>typeof row[key]==='number');}
 $effect(()=>{samples;metric;plot?.setData(data());});
 onMount(()=>{const seriesColor=color??token('--accent');plot=new uPlot({width:host.clientWidth||500,height:180,legend:{show:false},cursor:{show:true},scales:{x:{time:false,auto:false,range:()=>[-60,0]}},axes:[{stroke:token('--secondary'),grid:{stroke:token('--line')},splits:()=>LIVE_TIME_TICKS.map(tick=>tick.value),values:xValues},{stroke:token('--secondary'),grid:{stroke:token('--line')}}],series:[{}, {label,stroke:seriesColor,width:2}]},data(),host);const resize=new ResizeObserver(()=>plot?.setSize({width:host.clientWidth,height:180}));resize.observe(host);return()=>{resize.disconnect();plot?.destroy();plot=null;};});
</script>
<div class="chart-wrap"><div class="chart" bind:this={host}></div>{#if samples.length===0}<div class="empty">{emptyMessage}</div>{:else if !hasValue(samples,metric)}<div class="empty">{unavailableMessage}</div>{/if}</div>
<style>.chart-wrap{position:relative;width:100%;min-width:0;height:180px}.chart{width:100%;min-width:0;height:180px}.empty{position:absolute;inset:42% 0 auto;text-align:center;color:var(--secondary);font:inherit;pointer-events:none}</style>
