"""Exercise the real Tauri WebView and runtime through an existing WebDriver session.

Start WebKitWebDriver with TAURI_WEBVIEW_AUTOMATION=true on Linux, create a
session with webkitgtk:browserOptions.binary pointing to Veyra, and pass its ID.
Only the OS directory picker is bypassed; discovery, configure, processing,
events, rendering and controls all use the production implementation.
"""

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", default="http://127.0.0.1:4445")
    parser.add_argument("--session", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--soak-frames", type=int, default=0)
    args = parser.parse_args()
    endpoint = f"{args.driver}/session/{args.session}"

    def request(path, body=None):
        req = urllib.request.Request(
            endpoint + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=150) as response:
            value = json.load(response)["value"]
        if isinstance(value, dict) and "error" in value:
            raise RuntimeError(value)
        return value

    def js(script, *values):
        return request("/execute/sync", {"script": script, "args": list(values)})

    def click(text):
        return js(
            """
            const button=[...document.querySelectorAll('button')]
              .find(b=>b.textContent.trim()===arguments[0]);
            if(!button||button.disabled)throw new Error('Control unavailable: '+arguments[0]);
            button.click();return true;
        """,
            text,
        )

    def wait(script, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = js(script)
            if value:
                return value
            error = js("return document.querySelector('[role=alert]')?.innerText")
            if error:
                raise RuntimeError(error)
            time.sleep(0.25)
        raise TimeoutError(js("return document.body.innerText"))

    request("/timeouts", {"script": 120000})
    wait("return !!window.veyra", 30)
    js(
        """
        window.__flow={frames:[],telemetry:[],diagnostics:[],statuses:[]};
        window.veyra.onVisualization(f=>window.__flow.frames.push({
          index:f.metadata.index,points:f.metadata.points.count,cells:f.metadata.cells.count,
          bytes:f.payload.byteLength,schema:f.metadata.schema_version}));
        window.veyra.onEvent(e=>{
          if(e.type==='telemetry')window.__flow.telemetry.push(e);
          if(e.type==='diagnostics')window.__flow.diagnostics.push(e);
          if(e.type==='status')window.__flow.statuses.push(e);
        });
        const root=arguments[0];
        window.veyra.chooseDataset=dataset=>window.__TAURI_INTERNALS__.invoke(
          'choose_dataset',{dataset,root});
    """,
        args.dataset_root,
    )
    click("Live Mapping")
    assert js("return document.querySelector('.play-button').disabled")
    click("Datasets")
    js("""const s=document.querySelector('#dataset-format');s.value='semanticposs';
         s.dispatchEvent(new Event('change',{bubbles:true}));""")
    click("Choose dataset directory…")
    wait("return document.querySelector('#sequence')?.options.length>0")
    click("Open dataset & preview")
    wait(
        "return window.__flow.frames.length>0 && !document.querySelector('.map-empty')"
    )
    assert js(
        "return window.__flow.frames[0].points>0 && window.__flow.frames[0].cells>0"
    )
    wait("return !document.querySelector('.play-button').disabled")
    js("document.querySelector('.play-button').click();return true")
    wait("return document.querySelector('.status-pill')?.innerText==='Live'")
    js("document.querySelector('.play-button').click();return true")
    wait(
        "return document.querySelector('.status-pill')?.innerText.toLowerCase()==='paused'"
    )
    js("""const s=document.querySelector('[aria-label="Playback speed"]');
         s.value='2';s.dispatchEvent(new Event('change',{bubbles:true}));""")
    wait("return !document.querySelector('.play-button').disabled")
    click("Elevation")
    wait(
        "return document.querySelector('.layer.selected')?.textContent.includes('Elevation')"
    )
    extended_controls = []
    if args.extended:
        wait("return !document.querySelector('.play-button').disabled")
        js("""const s=document.querySelector('[aria-label="Seek frame"]');
             s.value='0';s.dispatchEvent(new Event('input',{bubbles:true}));
             s.dispatchEvent(new Event('change',{bubbles:true}));""")
        wait("return !document.querySelector('.play-button').disabled")
        for policy in ["uniform40", "distance_lod"]:
            js(
                """const s=document.querySelector('[aria-label="Mapping policy"]');
                 s.value=arguments[0];s.dispatchEvent(new Event('change',{bubbles:true}));""",
                policy,
            )
            wait("return !document.querySelector('.play-button').disabled")
            assert (
                js(
                    "return document.querySelector('[aria-label=\"Mapping policy\"]').value"
                )
                == policy
            )
        assert js("return window.__flow.statuses.at(-1)?.policy") == "distance_lod"
        click("Performance")
        for governor in ["conserve", "automatic"]:
            js(
                """const s=document.querySelector('#governor-override');
                 s.value=arguments[0];s.dispatchEvent(new Event('change',{bubbles:true}));""",
                governor,
            )
            wait("return !document.querySelector('#governor-override').disabled")
        click("Validation & benchmarks")
        click("Run session validation")
        wait(
            "return document.querySelector('.runtime-actions h3')?.innerText.includes('PASS')"
        )
        js("""const s=document.querySelector('#benchmark-count');s.value='1';
             s.dispatchEvent(new Event('input',{bubbles:true}));""")
        click("Run four-policy benchmark")
        wait(
            "return document.querySelector('.page-intro .chip')?.textContent==='COMPLETE'"
        )
        assert js(
            "return document.querySelector('.workspace-scroll').getBoundingClientRect().height>200"
        ), "Report must not collapse benchmark controls"
        extended_controls = ["seek", "policy", "governor", "validation", "benchmark"]
    if args.soak_frames:
        click("Live Mapping")
        for _ in range(args.soak_frames):
            wait("return !document.querySelector('[title=\"Step frame\"]').disabled")
            before = js("return window.__flow.telemetry.length")
            js("document.querySelector('[title=\"Step frame\"]').click();return true")
            wait(f"return window.__flow.telemetry.length>{before}")
        extended_controls.append("bounded repeated-frame replay")
    click("Dashboard")
    wait("return document.querySelectorAll('.dashboard-map canvas').length===3")
    assert not js("return !!document.querySelector('.dashboard-map-empty')")
    request(
        "/execute/async",
        {
            "script": "const done=arguments[arguments.length-1];requestAnimationFrame(()=>requestAnimationFrame(()=>done(true)));",
            "args": [],
        },
    )
    args.output.mkdir(parents=True, exist_ok=True)
    canvas = js(
        "return document.querySelector('.dashboard-map canvas').toDataURL('image/png')"
    )
    (args.output / "raw-canvas.png").write_bytes(
        base64.b64decode(canvas.split(",", 1)[1])
    )
    (args.output / "dashboard.png").write_bytes(
        base64.b64decode(request("/screenshot"))
    )
    evidence = js("return window.__flow")
    assert evidence["telemetry"], "No real telemetry received"
    assert not evidence["diagnostics"], evidence["diagnostics"]
    click("Datasets")
    if args.extended:
        before = js("return window.__flow.frames.length")
        click("Restart")
        wait(f"return window.__flow.frames.length>{before}")
        wait(
            "return [...document.querySelectorAll('button')].some(b=>b.textContent==='Stop session'&&!b.disabled)"
        )
        extended_controls.append("restart")
    click("Stop session")
    wait(
        "return document.querySelector('.notice')?.textContent.includes('Runtime stopped')"
    )
    evidence["controls"] = [
        "dataset discovery",
        "configure",
        "preview",
        "play",
        "pause",
        "speed",
        "layer",
        "dashboard render",
        "stop",
    ] + extended_controls
    evidence["dataset_root"] = args.dataset_root
    (args.output / "flow.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "pass",
                "frames": len(evidence["frames"]),
                "evidence": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
