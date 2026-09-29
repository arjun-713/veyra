<script lang="ts">
  import Icon from './Icon.svelte';
  import {datasetCapabilities, datasetFormats} from './dashboard';
  import {previewReadiness, sessionActive} from './setup';
  import {policies, type Json} from '../core';

  let {
    catalog, status, config, configText = $bindable(), dataset, sequence, preset, busy,
    onDataset, onSequence, onConfig, onPreset, chooseDataset, openPreview,
    importConfig, validateConfig, saveConfig, stopRuntime, restartRuntime,
  } = $props<{
    catalog: Json | null; status: Json; config: Json; configText: string;
    dataset: string; sequence: string; preset: string; busy: boolean;
    onDataset: (value: string) => void; onSequence: (value: string) => void;
    onConfig: (value: Json) => void; onPreset: (value: string) => void;
    chooseDataset: () => void; openPreview: () => void; importConfig: () => void;
    validateConfig: () => void; saveConfig: () => void;
    stopRuntime: () => void; restartRuntime: () => void;
  }>();
  const labels: Record<string, string> = {
    uniform5: 'Uniform 5 cm', uniform40: 'Uniform 40 cm',
    distance_lod: 'Distance LOD', utility_lod: 'Utility LOD',
  };
  const profiles = [
    ['LowResource', 'Low resource', 'Bounded replay for laptops'],
    ['Performance', 'Performance', 'Smaller display payloads'],
    ['Balanced', 'Balanced', 'More visual detail'],
    ['Quality', 'Quality', 'Highest display detail'],
  ];
  let readiness = $derived(previewReadiness(catalog, sequence, busy));
  let caps = $derived(datasetCapabilities(catalog, sequence));
  const number = (value: unknown) => typeof value === 'number' ? value.toLocaleString() : '—';
  const availability = (value: unknown) => value === true ? 'Available' : value === false ? 'Absent' : 'Unknown';
</script>

<div class="workspace-scroll session-page">
  <div class="page-intro">
    <div><h2>Set up a replay</h2><p>Choose your source. Review the settings. Open the first frame.</p></div>
    <button class="primary" disabled={!readiness.ready} aria-describedby="preview-help" onclick={openPreview}>
      <Icon name={busy ? 'loader' : 'play'} size={18}/>{busy ? 'Working…' : 'Open dataset & preview'}
    </button>
  </div>

  <div class="setup-layout">
    <section class="card setup-source" aria-labelledby="source-heading">
      <div class="setup-heading"><span class="step-index">1</span><div><h3 id="source-heading">Choose a dataset</h3><p>Veyra reads files in place. Nothing is uploaded.</p></div></div>
      <label for="dataset-format">Dataset format</label>
      <select id="dataset-format" value={dataset} disabled={busy} onchange={event => onDataset(event.currentTarget.value)}>
        {#each datasetFormats as [value, label]}<option value={value}>{label}</option>{/each}
      </select>
      <button class="directory-button" disabled={busy} onclick={chooseDataset}>
        <Icon name="folder" size={23}/><span><strong>{catalog ? 'Change dataset directory' : 'Choose dataset directory…'}</strong><small>{catalog?.root ?? 'Select the folder containing your dataset'}</small></span><Icon name="chevron" size={17}/>
      </button>
      {#if catalog}
        {#each catalog.diagnostics ?? [] as diagnostic}<p class="setup-diagnostic">{diagnostic}</p>{/each}
        <label for="sequence">Sequence</label>
        <select id="sequence" value={sequence} disabled={busy} onchange={event => onSequence(event.currentTarget.value)}>
          {#if !sequence}<option value="">Select a sequence</option>{/if}
          {#each catalog.sequences ?? [] as entry}
            <option value={entry.id} disabled={entry.frames <= 0}>{entry.id} · {number(entry.frames)} frames</option>
          {/each}
        </select>
        <dl class="dataset-facts">
          <div><dt>Frames</dt><dd>{number(caps.frames)}</dd></div>
          <div><dt>Labelled frames</dt><dd>{number(caps.labels)}</dd></div>
          <div><dt>Poses</dt><dd>{availability(caps.poses)}</dd></div>
          <div><dt>Timestamps</dt><dd>{availability(caps.timestamps)}</dd></div>
        </dl>
        <div class="capability-note"><Icon name="info" size={17}/><p><strong>{caps.semantic}</strong><br/>{caps.motion}</p></div>
      {:else}
        <p class="hint">Use the dataset root, not an individual scan. Generic sources require a manifest.json file.</p>
      {/if}
    </section>

    <section class="card setup-options" aria-labelledby="settings-heading">
      <div class="setup-heading"><span class="step-index">2</span><div><h3 id="settings-heading">Review replay settings</h3><p>Low resource is the default for a bounded laptop session.</p></div></div>
      <label for="display-profile">Display profile</label>
      <select id="display-profile" value={preset} disabled={busy} onchange={event => onPreset(event.currentTarget.value)}>
        {#each profiles as [value, label]}<option value={value}>{label}</option>{/each}
      </select>
      <p class="field-help">{profiles.find(([value]) => value === preset)?.[2] ?? 'Imported custom configuration'}</p>
      <label for="default-policy">Resolution policy</label>
      <select id="default-policy" value={config.map?.policy} disabled={busy} onchange={event => onConfig({...config, map: {...config.map, policy: event.currentTarget.value}})}>
        {#each policies as policy}<option value={policy}>{labels[policy]}</option>{/each}
      </select>
      <div class="setup-budget">
        <div><span>Points shown</span><strong>{number(config.visualization?.point_budget)}</strong></div>
        <div><span>Cells shown</span><strong>{number(config.visualization?.cell_budget)}</strong></div>
        <div><span>View updates</span><strong>{number(config.visualization?.update_hz)} Hz</strong></div>
      </div>
      <label class="toggle full-sequence"><input type="checkbox" disabled={busy} checked={config.playback?.full_sequence ?? false} onchange={event => onConfig({...config, playback: {...config.playback, full_sequence: event.currentTarget.checked}})}/>Replay the full sequence</label>
      <p class="field-help">{config.playback?.full_sequence ? 'All frames. This increases processing time and memory.' : `First ${config.playback?.frame_limit ?? 30} frames. Every point in each accepted frame still reaches the mapper.`}</p>
      <label for="playback-rate">Playback rate</label>
      <select id="playback-rate" value={config.playback?.fps ?? 10} disabled={busy} onchange={event => onConfig({...config, playback: {...config.playback, fps: Number(event.currentTarget.value)}})}>
        {#each [10, 15, 30, 60] as fps}<option value={fps}>{fps} FPS</option>{/each}
      </select>
      <p class="field-help">Live tick rate — compute-bound in practice. Smooth Replay presents cached snapshots at 15/30/60 FPS when the configured rate is one of those.</p>
    </section>
  </div>

  <section class="setup-review" aria-label="Open preview">
    <div class="setup-heading"><span class="step-index">3</span><div><h3>{readiness.ready ? 'Ready to preview' : 'Open your first frame'}</h3><p id="preview-help">{readiness.hint}</p></div></div>
  </section>

  <details class="card advanced-setup">
    <summary><Icon name="settings" size={18}/>Advanced configuration<span>JSON, validation and saved presets</span></summary>
    <p class="hint">Edit runtime stages and custom limits here. The same preview action above applies this configuration.</p>
    <textarea aria-label="Session configuration JSON" bind:value={configText} spellcheck="false" rows="14"></textarea>
    <div class="form-actions"><button disabled={busy} onclick={importConfig}><Icon name="import" size={16}/>Import preset</button><button disabled={busy} onclick={validateConfig}>Check configuration</button><button disabled={busy} onclick={saveConfig}><Icon name="save" size={16}/>Save preset</button></div>
  </details>

  {#if sessionActive(status)}
    <section class="session-management" aria-label="Current runtime session"><div><strong>Current session</strong><p>{status.dataset} · {status.sequence} · {status.state}</p></div><div><button disabled={busy} onclick={restartRuntime}><Icon name="restart" size={17}/>Restart runtime</button><button disabled={busy} onclick={stopRuntime}><Icon name="stop" size={17}/>Stop session</button></div></section>
  {/if}
</div>
